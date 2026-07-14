"""Unit tests for ccusage 20.x per-source usage tracking."""
import json
from unittest import mock

from summarize import usage


# ---- standard (claude namespace) sample ----
CLAUDE_RAW = {
    "daily": [{
        "date": "2026-06-13",
        "inputTokens": 100, "outputTokens": 50,
        "cacheCreationTokens": 10, "cacheReadTokens": 200,
        "totalTokens": 360, "totalCost": 1.5,
        "modelBreakdowns": [{
            "modelName": "claude-opus-4-6",
            "inputTokens": 100, "outputTokens": 50,
            "cacheCreationTokens": 10, "cacheReadTokens": 200, "cost": 1.5,
        }],
    }],
    "totals": {"inputTokens": 100, "outputTokens": 50,
               "cacheCreationTokens": 10, "cacheReadTokens": 200,
               "totalTokens": 360, "totalCost": 1.5},
}

# ---- codex namespace sample (models dict, costUSD, reasoning) ----
CODEX_RAW = {
    "daily": [{
        "date": "2026-04-01",
        "inputTokens": 436934, "outputTokens": 75382,
        "cacheReadTokens": 4548480, "reasoningOutputTokens": 51131,
        "totalTokens": 5060796, "costUSD": 3.36,
        "models": {"gpt-5.4": {
            "inputTokens": 436934, "outputTokens": 75382,
            "cacheReadTokens": 4548480, "reasoningOutputTokens": 51131,
            "totalTokens": 5060796,
        }},
    }],
    "totals": {"inputTokens": 436934, "outputTokens": 75382,
               "cacheReadTokens": 4548480, "totalTokens": 5060796,
               "costUSD": 3.36, "reasoningOutputTokens": 51131},
}


def test_normalize_standard_passthrough():
    out = usage._normalize_usage(CLAUDE_RAW, "claude")
    assert out["_source"] == "claude"
    day = out["daily"][0]
    assert day["date"] == "2026-06-13"
    assert day["totalCost"] == 1.5
    assert day["modelBreakdowns"][0]["modelName"] == "claude-opus-4-6"
    assert day["modelBreakdowns"][0]["cost"] == 1.5
    assert out["totals"]["totalTokens"] == 360


def test_normalize_codex_shape():
    out = usage._normalize_usage(CODEX_RAW, "codex")
    day = out["daily"][0]
    assert day["date"] == "2026-04-01"
    assert day["totalCost"] == 3.36           # costUSD -> totalCost
    assert day["reasoningOutputTokens"] == 51131
    mb = day["modelBreakdowns"][0]            # models{} -> modelBreakdowns[]
    assert mb["modelName"] == "gpt-5.4"
    assert mb["cost"] == 3.36                 # single model -> day cost
    assert mb["cacheReadTokens"] == 4548480
    assert out["totals"]["totalCost"] == 3.36


def test_normalize_period_fallback():
    raw = {"daily": [{"period": "2026-06-14", "totalTokens": 5, "totalCost": 0.1}],
           "totals": {}}
    out = usage._normalize_usage(raw, "gemini")
    assert out["daily"][0]["date"] == "2026-06-14"


def _completed(stdout="", code=0):
    m = mock.Mock()
    m.returncode = code
    m.stdout = stdout
    m.stderr = ""
    return m


def test_version_parse_modern_no_upgrade():
    with mock.patch.object(usage.shutil, "which", return_value="/usr/bin/ccusage"), \
         mock.patch.object(usage.subprocess, "run",
                           return_value=_completed("20.0.13")) as run:
        usage._USE_NPX = True            # force a known starting state
        usage._ensure_ccusage_global()
    assert usage._USE_NPX is False       # modern global -> use global
    assert run.call_count == 1           # only the --version probe ran


def test_version_old_triggers_silent_upgrade(monkeypatch):
    calls = []

    def fake_run(cmd, *a, **k):
        calls.append(cmd)
        if cmd[:2] == ["npm", "install"]:
            return _completed("", 0)
        # --version: report modern only after an npm install has happened
        ver = "20.0.13" if any(c[:2] == ["npm", "install"] for c in calls[:-1]) else "18.0.10"
        return _completed(ver)

    monkeypatch.setattr(usage.shutil, "which", lambda *_: "/usr/bin/ccusage")
    monkeypatch.setattr(usage.subprocess, "run", fake_run)
    usage._USE_NPX = False
    usage._ensure_ccusage_global()
    assert any(c[:2] == ["npm", "install"] for c in calls)
    assert usage._USE_NPX is False       # upgrade succeeded


def test_missing_falls_back_to_npx(monkeypatch):
    monkeypatch.setattr(usage.shutil, "which", lambda *_: None)
    monkeypatch.setattr(usage.subprocess, "run", lambda *a, **k: _completed("", 1))
    usage._USE_NPX = False
    usage._ensure_ccusage_global()
    assert usage._USE_NPX is True


def test_ccusage_cmd_switches_on_flag():
    usage._USE_NPX = False
    assert usage._ccusage_cmd(["codex", "daily"]) == ["ccusage", "codex", "daily"]
    usage._USE_NPX = True
    assert usage._ccusage_cmd(["codex", "daily"]) == \
        ["npx", "--yes", "ccusage@latest", "codex", "daily"]


UNIFIED_RAW = {
    "daily": [
        {"period": "2026-06-13", "agent": "all",
         "metadata": {"agents": ["claude", "codex"]}, "totalTokens": 1},
        {"period": "2026-06-14", "agent": "all",
         "metadata": {"agents": ["claude"]}, "totalTokens": 2},
    ],
    "totals": {},
}


def test_discover_sources_union():
    with mock.patch.object(usage, "_ensure_ccusage_global"), \
         mock.patch.object(usage, "_ccusage_cmd",
                           return_value=["ccusage", "daily", "--json"]), \
         mock.patch.object(usage.subprocess, "run",
                           return_value=_completed(json.dumps(UNIFIED_RAW))):
        assert usage.discover_sources() == ["claude", "codex"]


def test_discover_sources_failure_default():
    with mock.patch.object(usage, "_ensure_ccusage_global"), \
         mock.patch.object(usage, "_ccusage_cmd",
                           return_value=["ccusage", "daily", "--json"]), \
         mock.patch.object(usage.subprocess, "run",
                           return_value=_completed("", 1)):
        assert usage.discover_sources() == ["claude", "codex"]


def test_fetch_source_usage_normalizes():
    with mock.patch.object(usage, "_ccusage_cmd",
                           return_value=["ccusage", "codex", "daily", "--json", "--breakdown"]), \
         mock.patch.object(usage.subprocess, "run",
                           return_value=_completed(json.dumps(CODEX_RAW))):
        out = usage.fetch_source_usage("codex")
    assert out["_source"] == "codex"
    assert out["daily"][0]["totalCost"] == 3.36


def test_fetch_source_usage_empty_returns_none():
    with mock.patch.object(usage, "_ccusage_cmd",
                           return_value=["ccusage", "gemini", "daily"]), \
         mock.patch.object(usage.subprocess, "run",
                           return_value=_completed(json.dumps({"daily": [], "totals": {}}))):
        assert usage.fetch_source_usage("gemini") is None


def test_save_usage_file_roundtrip(tmp_path):
    norm = usage._normalize_usage(CLAUDE_RAW, "claude")
    with mock.patch.object(usage, "_get_device_name", return_value="dev1"):
        path = usage.save_usage_file(norm, "claude_code", tmp_path)
    assert path.name == "usage_claude_code_dev1.json"
    env = json.loads(path.read_text(encoding="utf-8"))
    assert env["source"] == "claude_code"
    assert env["usage"]["daily"][0]["date"] == "2026-06-13"


def test_save_usage_file_accumulates_history(tmp_path):
    """Dates that scrolled out of ccusage's ~30-day window must survive re-saves."""
    def _win(date_str, tokens, cost):
        return {"daily": [{"date": date_str, "totalTokens": tokens,
                           "totalCost": cost, "inputTokens": tokens,
                           "modelBreakdowns": [{"modelName": "m1",
                                                "inputTokens": tokens}]}],
                "totals": {"totalTokens": tokens, "totalCost": cost},
                "_source": "claude"}

    with mock.patch.object(usage, "_get_device_name", return_value="dev1"):
        usage.save_usage_file(_win("2026-05-01", 100, 1.0), "claude_code", tmp_path)
        # window slid: May 1 no longer returned, June 1 appears
        path = usage.save_usage_file(_win("2026-06-01", 50, 0.5), "claude_code", tmp_path)
        env = json.loads(path.read_text(encoding="utf-8"))
        assert [e["date"] for e in env["usage"]["daily"]] == ["2026-05-01", "2026-06-01"]
        assert env["usage"]["totals"]["totalTokens"] == 150
        assert env["usage"]["totals"]["modelBreakdowns"][0]["inputTokens"] == 150
        # same date re-fetched: newer entry wins, no duplicate
        path = usage.save_usage_file(_win("2026-06-01", 70, 0.7), "claude_code", tmp_path)
        env = json.loads(path.read_text(encoding="utf-8"))
        assert [e["date"] for e in env["usage"]["daily"]] == ["2026-05-01", "2026-06-01"]
        assert env["usage"]["daily"][1]["totalTokens"] == 70
        assert env["usage"]["totals"]["totalTokens"] == 170


def test_load_reads_new_and_legacy(tmp_path):
    import datetime as _dt
    # new-format file
    norm = usage._normalize_usage(CLAUDE_RAW, "claude")
    (tmp_path / "usage_claude_code_dev1.json").write_text(json.dumps({
        "device_name": "dev1", "source": "claude_code", "usage": norm,
    }), encoding="utf-8")
    # legacy codex file
    codex_norm = usage._normalize_usage(CODEX_RAW, "codex")
    (tmp_path / "codex_usage_dev2.json").write_text(json.dumps({
        "device_name": "dev2", "ccusage": codex_norm, "_source": "codex",
    }), encoding="utf-8")

    got = usage.load_ccusage_for_date(tmp_path, _dt.date(2026, 6, 13))
    assert any(g["_source"] == "claude_code" for g in got)
    got2 = usage.load_ccusage_for_date(tmp_path, _dt.date(2026, 4, 1))
    assert any(g["_source"] == "codex" for g in got2)


def test_refresh_snapshots_per_source(tmp_path, monkeypatch):
    monkeypatch.setattr(usage, "discover_sources", lambda: ["claude", "codex"])
    monkeypatch.setattr(usage, "fetch_source_usage",
                        lambda s: usage._normalize_usage(
                            CLAUDE_RAW if s == "claude" else CODEX_RAW, s))
    monkeypatch.setattr(usage, "_get_device_name", lambda: "devX")
    monkeypatch.setattr(usage, "_rclone_upload", lambda *a, **k: None)

    usage._refresh_usage_snapshots(tmp_path)
    names = sorted(p.name for p in tmp_path.glob("usage_*.json"))
    assert names == ["usage_claude_code_devX.json", "usage_codex_devX.json"]


def test_chart_multi_source_smoke(tmp_path):
    from summarize import charts
    from datetime import date
    raw_by_source = {
        "claude_code": usage._normalize_usage(CLAUDE_RAW, "claude"),
        "codex": usage._normalize_usage(CODEX_RAW, "codex"),
    }
    by_source = {k: usage._merge_token_usages([{"device_name": "d", "usage": v}])
                 for k, v in raw_by_source.items()}
    out = charts.generate_daily_chart(by_source, date(2026, 6, 13),
                                      output_dir=tmp_path)
    # matplotlib may be absent -> None acceptable; if present, a file exists
    assert out is None or out.exists()
