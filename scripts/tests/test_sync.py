"""Unit tests for scripts/sync.py category rename — no rclone/network.

Run: python -m pytest scripts/tests/test_sync.py -q
"""

import sync


def test_benchmark_replaces_test_category():
    assert "benchmark" in sync.SYNC_DIRS
    assert "benchmark" in sync.SYNC_FILES
    assert "test" not in sync.SYNC_DIRS
    assert "test" not in sync.SYNC_FILES


def test_benchmark_remote_paths():
    assert sync.SYNC_DIRS["benchmark"] == [
        ("outputs/data/benchmark", "benchmark/data"),
    ]
    assert sync.SYNC_FILES["benchmark"] == [
        ("outputs/data/benchmark/results.csv", "benchmark/data/benchmark_results.csv"),
    ]


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
