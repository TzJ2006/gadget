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


# ─── pull must not clobber the append-only ledger ────────────────────

def test_the_ledger_is_declared_append_only():
    """Repointing the mapping at the real file made pull dangerous.

    A pull is a whole-file copy. While the mapping named a path nothing
    writes that was inert; pointing it at the real ledger meant a pull would
    discard every row this machine added since its last push — the opposite
    of what an accumulation ledger is for.
    """
    from benchmark.core import BenchmarkResults
    from common.paths import GADGET_ROOT

    ledger = BenchmarkResults("").output_path.relative_to(GADGET_ROOT).as_posix()
    assert ledger in sync.APPEND_ONLY_FILES


def test_merge_keeps_every_local_row(tmp_path):
    local = tmp_path / "local.csv"
    remote = tmp_path / "remote.csv"
    local.write_text("ts,gpu,flops\n1,A,10\n2,B,20\n", encoding="utf-8")
    remote.write_text("ts,gpu,flops\n3,C,30\n", encoding="utf-8")

    ok, msg = sync.merge_append_only_csv(remote, local)
    assert ok, msg
    rows = local.read_text(encoding="utf-8").splitlines()
    assert rows[0] == "ts,gpu,flops"
    assert rows[1:] == ["1,A,10", "2,B,20", "3,C,30"], rows


def test_merge_does_not_duplicate_rows_already_present(tmp_path):
    local = tmp_path / "local.csv"
    remote = tmp_path / "remote.csv"
    local.write_text("ts,gpu,flops\n1,A,10\n2,B,20\n", encoding="utf-8")
    remote.write_text("ts,gpu,flops\n1,A,10\n2,B,20\n", encoding="utf-8")

    ok, _ = sync.merge_append_only_csv(remote, local)
    assert ok
    assert local.read_text(encoding="utf-8").splitlines()[1:] == ["1,A,10", "2,B,20"]


def test_merge_never_shrinks_the_ledger(tmp_path):
    """The property that matters: pull may add rows, never remove them."""
    local = tmp_path / "local.csv"
    remote = tmp_path / "remote.csv"
    local.write_text("ts,gpu,flops\n" + "".join(f"{i},A,{i}\n" for i in range(50)),
                     encoding="utf-8")
    before = len(local.read_text(encoding="utf-8").splitlines())
    remote.write_text("ts,gpu,flops\n99,Z,99\n", encoding="utf-8")

    sync.merge_append_only_csv(remote, local)
    after = len(local.read_text(encoding="utf-8").splitlines())
    assert after >= before, f"pull shrank the ledger: {before} -> {after}"
    assert after == before + 1


def test_merge_refuses_a_mismatched_header(tmp_path):
    """Appending rows under a different header puts values in wrong columns."""
    local = tmp_path / "local.csv"
    remote = tmp_path / "remote.csv"
    local.write_text("ts,gpu,flops\n1,A,10\n", encoding="utf-8")
    remote.write_text("ts,flops,gpu\n2,20,B\n", encoding="utf-8")

    ok, msg = sync.merge_append_only_csv(remote, local)
    assert not ok and "表头" in msg
    assert local.read_text(encoding="utf-8").splitlines()[1:] == ["1,A,10"]


def test_merge_handles_a_local_file_without_a_trailing_newline(tmp_path):
    local = tmp_path / "local.csv"
    remote = tmp_path / "remote.csv"
    local.write_text("ts,gpu,flops\n1,A,10", encoding="utf-8")   # no final \n
    remote.write_text("ts,gpu,flops\n2,B,20\n", encoding="utf-8")

    ok, _ = sync.merge_append_only_csv(remote, local)
    assert ok
    assert local.read_text(encoding="utf-8").splitlines()[1:] == ["1,A,10", "2,B,20"]


def test_pull_routes_the_ledger_through_the_merge_not_a_copy():
    """Reachability: the append-only branch must be in sync_files' pull path."""
    import ast
    import inspect

    src = inspect.getsource(sync.sync_files)
    assert "APPEND_ONLY_FILES" in src, "sync_files still copies every file blindly"
    tree = ast.parse(src)
    names = {getattr(n.func, "id", None) or getattr(n.func, "attr", None)
             for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert "merge_append_only_csv" in names


# ─── status must not go blind on a file-only category ────────────────

def test_status_reports_file_mappings_too():
    """Emptying SYNC_DIRS['benchmark'] made `status --category benchmark`
    print nothing at all, because status only ever walked SYNC_DIRS."""
    import inspect

    src = inspect.getsource(sync.cmd_status)
    assert "SYNC_FILES" in src, (
        "cmd_status ignores SYNC_FILES, so a category whose mappings are all "
        "files reports nothing")
