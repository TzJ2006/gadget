"""The results CSV is an append-only ledger, and the timer rejects outliers.

This is the benchmark tool's first test suite. It had none — 3126 lines with no
tests/ directory, while AGENTS.md states the append rule as hard ("results
append to benchmark_results.csv by design — never rewrite or dedupe it") and the
file itself is outside version control. A refactor that turned append into
overwrite would delete accumulated cross-machine history with nothing to catch
it and nothing to restore from.

Pure-mock: no torch, no GPU, no network. numpy is the only real dependency,
and it already ships in the benchmark extra.
"""

import csv

import pytest

from benchmark.core import (
    BenchmarkResults,
    RobustTimer,
    calculate_flops_gemm,
    calculate_flops_scalar,
    fmt_flops,
)

SYSTEM = {
    "cpu": {"model": "Test CPU", "cores": 8, "frequency": "3.0GHz"},
    "gpus": [{"vendor": "NVIDIA", "model": "Test GPU", "memory_gb": 24,
              "compute_capability": "8.9"}],
    "software": {"os": "Linux", "python": "3.11", "torch": "2.0", "cuda": "12.1"},
}


def _result(name, flops=1e12, median=0.5):
    return {"name": name, "type": "gemm", "backend": "cuda", "dtype": "fp32",
            "matrix_size": 4096, "flops_per_sec": flops, "iterations": 10,
            "stats": {"median": median}}


def _rows(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ─── the ledger ──────────────────────────────────────────────────────

def test_second_save_appends_and_leaves_the_first_rows_byte_identical(tmp_path):
    csv_path = tmp_path / "benchmark_results.csv"

    r = BenchmarkResults(str(csv_path))
    r.add(_result("run-one"), SYSTEM)
    r.save()
    after_first = csv_path.read_bytes()

    r.add(_result("run-two"), SYSTEM)
    r.save()
    after_second = csv_path.read_bytes()

    assert after_second.startswith(after_first), \
        "the first run's bytes must survive verbatim — this file is the history"
    rows = _rows(csv_path)
    assert [x["benchmark_name"] for x in rows] == ["run-one", "run-two"]


def test_header_is_written_once(tmp_path):
    csv_path = tmp_path / "results.csv"
    r = BenchmarkResults(str(csv_path))
    for name in ("a", "b", "c"):
        r.add(_result(name), SYSTEM)
        r.save()

    text = csv_path.read_text(encoding="utf-8")
    assert text.count("benchmark_name") == 1
    assert len(_rows(csv_path)) == 3


def test_row_count_is_the_sum_of_every_run(tmp_path):
    csv_path = tmp_path / "results.csv"
    r = BenchmarkResults(str(csv_path))
    for batch in range(3):
        for i in range(4):
            r.add(_result(f"b{batch}-{i}"), SYSTEM)
        r.save()
    assert len(_rows(csv_path)) == 12


def test_missing_parent_directory_is_created(tmp_path):
    """A fresh checkout has no outputs dir; append mode will not make one."""
    csv_path = tmp_path / "does" / "not" / "exist" / "results.csv"
    r = BenchmarkResults(str(csv_path))
    r.add(_result("first-ever"), SYSTEM)
    r.save()
    assert csv_path.exists()
    assert len(_rows(csv_path)) == 1


def test_saving_nothing_does_not_create_a_file(tmp_path):
    csv_path = tmp_path / "results.csv"
    BenchmarkResults(str(csv_path)).save()
    assert not csv_path.exists()


def test_save_clears_the_buffer_so_a_second_save_cannot_duplicate(tmp_path):
    csv_path = tmp_path / "results.csv"
    r = BenchmarkResults(str(csv_path))
    r.add(_result("once"), SYSTEM)
    r.save()
    r.save()  # nothing buffered — must be a no-op, not a second copy
    assert len(_rows(csv_path)) == 1


def test_missing_gpu_info_degrades_to_placeholders(tmp_path):
    """A CPU-only machine still records a usable row."""
    csv_path = tmp_path / "results.csv"
    r = BenchmarkResults(str(csv_path))
    r.add(_result("cpu-only"), {"cpu": {}, "gpus": [], "software": {}})
    r.save()

    row = _rows(csv_path)[0]
    assert row["gpu_vendor"] == "N/A"
    assert row["gpu_model"] == "N/A"
    assert row["cpu_model"] == "Unknown"
    assert row["benchmark_name"] == "cpu-only"


# ─── the timer ───────────────────────────────────────────────────────

def test_one_slow_sample_does_not_move_the_median():
    """Background load produces the odd very slow iteration; IQR drops it."""
    samples = [0.010] * 40 + [5.0]
    it = iter(samples)
    stats = RobustTimer(warmup_iters=0, measure_iters=len(samples)).time(lambda: next(it))

    assert stats["outliers_removed"] == 1
    assert stats["max"] < 1.0, "the 5s sample should have been rejected"
    assert stats["median"] == pytest.approx(0.010, abs=1e-6)


def test_warmup_runs_but_is_not_measured():
    calls = {"n": 0}

    def tick():
        calls["n"] += 1
        return 0.001

    stats = RobustTimer(warmup_iters=7, measure_iters=3).time(tick)
    assert calls["n"] == 10          # 7 warmup + 3 measured
    assert stats["actual_iters"] == 3


def test_target_duration_calibrates_the_iteration_count():
    timer = RobustTimer(warmup_iters=0, measure_iters=1, target_duration=1.0)
    timer.time(lambda: 0.01)
    assert timer.measure_iters == 100   # 1.0s / 0.01s


# ─── the arithmetic ──────────────────────────────────────────────────

def test_gemm_flops_is_two_n_cubed_per_iteration():
    assert calculate_flops_gemm(1024, 1) == 2 * 1024 ** 3
    assert calculate_flops_gemm(1024, 3) == 3 * 2 * 1024 ** 3


def test_scalar_flops_counts_iterations():
    assert calculate_flops_scalar(5) > 0


def test_fmt_flops_picks_the_unit():
    assert "TFLOPS" in fmt_flops(1.5e12)
    assert "GFLOPS" in fmt_flops(1.5e9)
