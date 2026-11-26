"""Scan shortcuts must not change results: mtime pruning, day index, tail flag, merge args."""

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

from summarize import records
from summarize.daily_export import _tail_finalized
from summarize.daily_merge import _merge_single_date
from summarize.parsers import discover_all_dates


def _claude_file(path: Path, stamp: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = {"type": "user", "timestamp": stamp, "uuid": path.stem,
            "message": {"role": "user", "content": "hi"}}
    path.write_text(json.dumps(line) + "\n", encoding="utf-8")
    return path


def test_load_records_skips_files_last_written_before_start_day(tmp_path):
    day = date(2026, 3, 10)
    stamp = datetime(2026, 3, 10, 12).astimezone().isoformat()
    old = _claude_file(tmp_path / "p" / "old.jsonl", stamp)
    _claude_file(tmp_path / "p" / "new.jsonl", stamp)
    before = datetime(2026, 3, 9, 23).timestamp()
    os.utime(old, (before, before))
    rows, _ = records.load_records("claude_code", tmp_path, on_date=day)
    assert {r["conversation_id"] for r in rows} == {"new"}
    rows, _ = records.load_records("claude_code", old, on_date=day)  # explicit file is never pruned
    assert {r["conversation_id"] for r in rows} == {"old"}


def test_codex_project_only_read_for_matching_files(tmp_path):
    entry = {"type": "event_msg", "timestamp": datetime(2026, 3, 10, 12).astimezone().isoformat(),
             "payload": {"type": "user_message", "message": "hi"}}
    (tmp_path / "rollout-a.jsonl").write_text(json.dumps(entry) + "\n", encoding="utf-8")
    with mock.patch.object(records, "_extract_codex_project", return_value="proj") as extract:
        rows, _ = records.load_records("codex", tmp_path, on_date=date(2026, 3, 11))
    assert rows == [] and extract.call_count == 0


def test_discover_all_dates_reuses_day_index_until_file_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr("summarize.parsers._DAY_INDEX_PATH", tmp_path / "day_index.json")
    stamp = datetime(2026, 3, 10, 12).astimezone().isoformat()
    log = _claude_file(tmp_path / ".claude" / "projects" / "p" / "s.jsonl", stamp)
    assert discover_all_dates() == {date(2026, 3, 10)}
    with mock.patch.object(records, "load_records", side_effect=AssertionError("reparsed")):
        assert discover_all_dates() == {date(2026, 3, 10)}
    later = datetime(2026, 3, 12, 12).astimezone().isoformat()
    _claude_file(log, later)
    os.utime(log, ns=(log.stat().st_mtime_ns + 10**9,) * 2)
    assert discover_all_dates() == {date(2026, 3, 12)}


def test_tail_finalized_reads_trailing_flag(tmp_path):
    path = tmp_path / "log.json"
    for data, expected in [({"a": 1, "_finalized": True}, True),
                           ({"a": 1, "_finalized": False}, False),
                           ({"a": 1}, None),
                           ({"a": {"_finalized": True}}, None)]:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        assert _tail_finalized(path) is expected


def test_merge_single_date_passes_synced_files_instead_of_resyncing(tmp_path):
    files = [tmp_path / "2026-03-10_a.json", tmp_path / "2026-03-10.json", tmp_path / "2026-03-10_b.json"]
    for p in files:
        p.write_text("{}", encoding="utf-8")
    with mock.patch("summarize.daily_merge.subprocess.run",
                    return_value=mock.Mock(returncode=0)) as run:
        _merge_single_date("2026-03-10", ["py", "merge"], {"2026-03-10": files}, 10, tmp_path)
    assert run.call_args.args[0] == ["py", "merge", "--date", "2026-03-10",
                                     str(files[0]), str(files[2])]


def test_sync_all_retries_a_failed_day_once(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    import summarize.daily_merge as dm
    log = tmp_path / "2026-03-10_pc.json"
    log.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(dm, "_rclone_download_logs", lambda *a: [log])
    monkeypatch.setattr(dm, "_rclone_download_reports", lambda *a: None)
    monkeypatch.setattr(dm, "LOGS_DIR", tmp_path)
    calls = []
    monkeypatch.setattr(dm, "_wait_for_ollama", lambda *a: None)
    monkeypatch.setattr(dm, "_merge_single_date",
                        lambda d, *a: (calls.append(d), (d, len(calls) > 1, ""))[1])
    args = SimpleNamespace(output=str(tmp_path), force=True, before=None, newest_first=False, workers=1,
                           timeout=10, api=None, no_cache=False, deploy=False, hugo_site=None)
    dm._cmd_merge_sync_all(args)
    assert calls == ["2026-03-10", "2026-03-10"]
    assert "成功 1, 失败 0" in capsys.readouterr().out


def test_merge_single_date_retries_when_report_is_bad(tmp_path, monkeypatch):
    import json, subprocess
    import summarize.daily_merge as dm
    reports = tmp_path / "reports"; reports.mkdir()
    runs = []

    def fake_run(cmd, **kw):
        runs.append(1)
        body = {"parse_error": True} if len(runs) == 1 else {"conversation_summaries": [{"title": "x"}]}
        (reports / "2026-03-10.json").write_text(json.dumps(body), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(dm.subprocess, "run", fake_run)
    monkeypatch.setattr(dm, "_wait_for_ollama", lambda *a: None)
    d, ok, _ = dm._merge_single_date("2026-03-10", ["py"], {}, 10, tmp_path, reports)
    assert ok and len(runs) == 2

    runs.clear()
    monkeypatch.setattr(dm.subprocess, "run", lambda cmd, **kw: (runs.append(1), subprocess.CompletedProcess(cmd, 0))[1])
    (reports / "2026-03-11.json").write_text(json.dumps({"conversation_summaries": [1]}), encoding="utf-8")
    import os; os.utime(reports / "2026-03-11.json", (0, 0))   # stale report from an older run
    assert dm._merge_single_date("2026-03-11", ["py"], {}, 10, tmp_path, reports)[1] is False
    assert len(runs) == 2
