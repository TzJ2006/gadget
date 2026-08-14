"""Tests for summarize.period_report and the weekly/monthly/formatter wrappers."""

import argparse
import inspect
from datetime import date, datetime
from pathlib import Path

from common.llm import DEFAULT_BACKEND, LLM_BACKENDS
from summarize.formatter import generate_hugo_post
from summarize.monthly_summary import (
    _call_monthly_summarize_chunked,
    generate_monthly_hugo_post,
)
from summarize.period_report import (
    CHUNK_CHARS,
    TIMEOUT_DAILY,
    TIMEOUT_MONTHLY,
    TIMEOUT_WEEKLY,
    add_generate_arguments,
    compute_source_hash,
    generate_period_hugo_post,
    hugo_datetime,
    load_period_cache,
    reshape_usage_for_chart,
    resolved_chunk_chars,
    resolved_timeout_weekly,
    save_period_cache,
)
from summarize.weekly_summary import (
    _call_weekly_summarize_chunked,
    generate_weekly_hugo_post,
)


def test_named_constants():
    assert CHUNK_CHARS == 150_000
    assert TIMEOUT_DAILY == 600
    assert TIMEOUT_WEEKLY == 900
    assert TIMEOUT_MONTHLY == 1800


def test_chunk_chars_config_fallback(monkeypatch):
    monkeypatch.setattr("summarize.period_report._load_config",
                        lambda: {"chunk_chars": 99})
    assert resolved_chunk_chars() == 99
    monkeypatch.setattr("summarize.period_report._load_config", lambda: {})
    assert resolved_chunk_chars() == CHUNK_CHARS


def test_timeout_weekly_config_fallback(monkeypatch):
    monkeypatch.setattr("summarize.period_report._load_config",
                        lambda: {"timeout_weekly": 42})
    assert resolved_timeout_weekly() == 42
    monkeypatch.setattr("summarize.period_report._load_config", lambda: {})
    assert resolved_timeout_weekly() == TIMEOUT_WEEKLY


def test_hugo_datetime_uses_local_offset():
    d = date(2026, 8, 14)
    stamp = hugo_datetime(d, hour=23, minute=59)
    local = datetime(2026, 8, 14, 23, 59, 0).astimezone()
    off = local.strftime("%z")
    expected_off = off[:3] + ":" + off[3:] if off else "+00:00"
    assert stamp == f"2026-08-14T23:59:00{expected_off}"
    assert stamp[10] == "T"


def _capture_write_bilingual(monkeypatch, tmp_path):
    captured = {}

    def fake_wb(hugo_site, rel, content, **kwargs):
        captured["rel"] = Path(rel)
        captured["content"] = content
        captured["kwargs"] = kwargs
        p = tmp_path / "en.md"
        p.write_text(content, encoding="utf-8")
        return p, None

    monkeypatch.setattr("summarize.period_report.write_bilingual", fake_wb)
    monkeypatch.setattr("summarize.period_report.resolve_site_content_dir",
                        lambda *a, **k: tmp_path)
    return captured


def test_generate_period_hugo_post_goes_through_write_bilingual(tmp_path, monkeypatch):
    captured = _capture_write_bilingual(monkeypatch, tmp_path)
    path = generate_period_hugo_post(
        "> A week of work\n\nBody",
        tmp_path / "site",
        title="Weekly Summary 2026-W12",
        post_date=date(2026, 3, 22),
        hour=23, minute=59,
        keywords=["Bug Journal", "Weekly Summary"],
        fallback_summary="fallback",
        content_parts=("bugJournal", "weekly"),
        filename="2026-W12-weekly.md",
    )
    assert path.exists()
    stamp = hugo_datetime(date(2026, 3, 22), hour=23, minute=59)
    assert f"date: {stamp}" in captured["content"]
    assert 'summary: "A week of work"' in captured["content"]
    assert captured["rel"] == Path("bugJournal") / "weekly" / "2026-W12-weekly.md"
    assert "gadget_generated" not in captured["content"]  # stamped inside write_bilingual


def test_daily_weekly_monthly_wrappers_use_local_tz(tmp_path, monkeypatch):
    captured = _capture_write_bilingual(monkeypatch, tmp_path)
    body = "> hello\n\ntext"

    generate_hugo_post(body, date(2026, 8, 14), tmp_path / "site")
    daily_stamp = hugo_datetime(date(2026, 8, 14), hour=0)
    assert f"date: {daily_stamp}" in captured["content"]

    generate_weekly_hugo_post(body, 2026, 12, tmp_path / "site")
    weekly_stamp = hugo_datetime(date(2026, 3, 22), hour=23, minute=59)
    assert f"date: {weekly_stamp}" in captured["content"]

    generate_monthly_hugo_post(body, 2026, 2, tmp_path / "site")
    monthly_stamp = hugo_datetime(date(2026, 2, 28), hour=23, minute=59)
    assert f"date: {monthly_stamp}" in captured["content"]


def test_hugo_post_api_default_is_ollama():
    assert inspect.signature(generate_hugo_post).parameters["api"].default == DEFAULT_BACKEND
    assert inspect.signature(generate_weekly_hugo_post).parameters["api"].default == DEFAULT_BACKEND
    assert inspect.signature(generate_monthly_hugo_post).parameters["api"].default == DEFAULT_BACKEND
    assert DEFAULT_BACKEND == "ollama" or DEFAULT_BACKEND in LLM_BACKENDS


def test_dead_single_shot_wrappers_removed():
    import summarize.weekly_summary as weekly
    import summarize.monthly_summary as monthly
    assert not hasattr(weekly, "_call_weekly_summarize")
    assert not hasattr(monthly, "_call_monthly_summarize")
    assert hasattr(weekly, "_call_weekly_summarize_chunked")
    assert hasattr(monthly, "_call_monthly_summarize_chunked")


def test_api_argparse_uses_llm_backends():
    parser = argparse.ArgumentParser()
    add_generate_arguments(parser, timeout_default=TIMEOUT_WEEKLY)
    action = next(a for a in parser._actions if a.dest == "api")
    assert tuple(action.choices) == LLM_BACKENDS


def test_period_cache_roundtrip(tmp_path):
    reports = [{"date": "2026-03-01", "summary": "a", "_source_file": "x"}]
    h = compute_source_hash(reports)
    save_period_cache(tmp_path, "2026-W09", {"summary": "cached"}, h)
    hit = load_period_cache(tmp_path, "2026-W09", h)
    assert hit == {"summary": "cached"}
    assert load_period_cache(tmp_path, "2026-W09", "stale") is None


def test_compute_source_hash_ignores_underscore_keys():
    a = [{"date": "2026-01-01", "summary": "s", "_source_file": "one"}]
    b = [{"date": "2026-01-01", "summary": "s", "_source_file": "two"}]
    assert compute_source_hash(a) == compute_source_hash(b)


def test_reshape_usage_for_chart():
    usage = {
        "claude_code": {
            "totals": {"totalTokens": 10, "totalCost": 1.5},
            "model_breakdown": {"sonnet": {"cost": 1.5, "inputTokens": 10}},
        },
        "empty": {"totals": {}},
    }
    out = reshape_usage_for_chart(usage)
    assert "claude_code" in out and "empty" not in out
    assert out["claude_code"]["modelBreakdowns"][0]["modelName"] == "sonnet"


def test_chunked_wrappers_still_callable():
    assert callable(_call_weekly_summarize_chunked)
    assert callable(_call_monthly_summarize_chunked)
