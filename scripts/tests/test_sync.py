"""Unit tests for scripts/sync.py category rename — no rclone/network.

Run: python -m pytest scripts/tests/test_sync.py -q
"""

import sync


def test_benchmark_replaces_test_category():
    assert "benchmark" in sync.SYNC_DIRS
    assert "benchmark" in sync.SYNC_FILES
    assert "test" not in sync.SYNC_DIRS
    assert "test" not in sync.SYNC_FILES


def test_benchmark_backup_points_at_the_ledger_the_tool_actually_writes():
    """Cross-checked against the producer, not copied from the sync map.

    These drifted apart: sync mapped outputs/data/benchmark/results.csv, a path
    nothing has ever written, so `push --category benchmark` copied nothing —
    and the previous version of this test asserted that same wrong path, so the
    suite stayed green. Deriving the expected value from BenchmarkResults means
    changing either side without the other fails here.
    """
    from benchmark.core import BenchmarkResults
    from common.paths import GADGET_ROOT

    ledger = BenchmarkResults("").output_path
    expected = ledger.relative_to(GADGET_ROOT).as_posix()

    sources = [local for local, _ in sync.SYNC_FILES["benchmark"]]
    assert sources == [expected]
    assert (GADGET_ROOT / expected).exists(), f"{expected} does not exist"


def test_benchmark_has_no_directory_mappings():
    """The ledger is a file and the submission queue is tracked in git."""
    assert sync.SYNC_DIRS["benchmark"] == []


def test_no_synced_file_points_into_a_directory_nothing_writes():
    """Every file source must be either present or under a real output tree.

    The benchmark entry failed both: the path did not exist and no code ever
    created it.
    """
    from common.paths import GADGET_ROOT

    missing = []
    for category, entries in sync.SYNC_FILES.items():
        for local, _remote in entries:
            path = GADGET_ROOT / local
            if path.exists():
                continue
            # A personal file may legitimately be absent from a given checkout,
            # but its parent directory must at least be real.
            if not path.parent.exists():
                missing.append(f"{category}: {local} (parent does not exist)")
    assert not missing, "sync sources pointing nowhere: " + "; ".join(missing)


def test_test_alias_resolves_to_benchmark():
    assert sync.resolve_category("test") == "benchmark"
    assert sync.resolve_category("benchmark") == "benchmark"
    assert sync.resolve_category("summarize") == "summarize"
    assert sync.resolve_category(None) is None


def test_rclone_choices_include_alias():
    choices = sync.rclone_category_choices()
    assert "benchmark" in choices
    assert "test" in choices
    assert choices.count("benchmark") == 1
