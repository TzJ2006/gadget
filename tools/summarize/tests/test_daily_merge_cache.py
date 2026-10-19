"""daily merge cache writes stay inside the flag that asked for them.

``--no-cache`` must force a fresh summary call and leave
``outputs/cache/summarize/<date>.json`` untouched. The default path still
writes that file. LLM, rclone, and usage snapshots are stubbed.
"""

import json
from argparse import Namespace

from common import config as gadget_config
from summarize.daily_merge import cmd_merge

DATE = "2020-01-02"


def _write_log(path):
    path.write_text(json.dumps({
        "date": DATE,
        "device": {"device_name": "pa31"},
        "_finalized": True,
        "conversations": [{
            "id": "c1",
            "messages": [{"role": "user", "content": "hello"}],
        }],
    }, ensure_ascii=False), encoding="utf-8")


def _args(log_path, output, *, no_cache):
    return Namespace(
        sync_all=False,
        sync=False,
        log_files=[str(log_path)],
        date=DATE,
        api="ollama",
        output=str(output),
        deploy=False,
        hugo_site="",
        timeout=30,
        no_cache=no_cache,
        force=False,
        workers=1,
        before=None,
    )


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("GADGET_CONFIG", str(tmp_path / "no-config.json"))
    monkeypatch.delenv("SUMMARIZE_LOGS_DIR", raising=False)
    monkeypatch.delenv("SUMMARIZE_REPORTS_DIR", raising=False)
    gadget_config.clear_cache()
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    monkeypatch.setattr("summarize.daily_merge._DEFAULT_CACHE_DIR", cache_dir)
    monkeypatch.setattr("summarize.daily_merge._rclone_upload", lambda *a, **k: None)
    monkeypatch.setattr(
        "summarize.daily_merge.load_ccusage_for_date", lambda *a, **k: [])
    calls = []

    def fake_call(*args, **kwargs):
        calls.append(kwargs.get("chunk_cache_dir"))
        return {"summary": "fresh-from-llm", "tasks": []}

    monkeypatch.setattr("summarize.daily_merge._call_summarize", fake_call)
    return cache_dir, calls


def test_no_cache_does_not_write_summary_cache(tmp_path, monkeypatch):
    cache_dir, calls = _isolate(tmp_path, monkeypatch)
    sentinel = cache_dir / f"{DATE}.json"
    sentinel.write_text('{"summary":"old"}', encoding="utf-8")
    log = tmp_path / "log.json"
    _write_log(log)

    cmd_merge(_args(log, tmp_path / "reports", no_cache=True))

    assert calls, "expected a fresh summary call when --no-cache is set"
    assert calls[0] is None
    assert sentinel.read_text(encoding="utf-8") == '{"summary":"old"}'
    report = json.loads((tmp_path / "reports" / f"{DATE}.json").read_text(encoding="utf-8"))
    assert report["summary"] == "fresh-from-llm"


def test_default_merge_still_writes_summary_cache(tmp_path, monkeypatch):
    cache_dir, calls = _isolate(tmp_path, monkeypatch)
    log = tmp_path / "log.json"
    _write_log(log)

    cmd_merge(_args(log, tmp_path / "reports", no_cache=False))

    assert calls
    cached = json.loads((cache_dir / f"{DATE}.json").read_text(encoding="utf-8"))
    assert cached["summary"] == "fresh-from-llm"
