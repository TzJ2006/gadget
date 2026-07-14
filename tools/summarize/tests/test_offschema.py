"""Regression tests for off-schema LLM output (list where dict expected) and
parse-failed chunk handling — see the 2026-06 monthly crash at
generate_monthly_markdown (ai_collaboration_trends arrived as a list)."""

import pytest
from unittest.mock import patch

from common.llm import (
    LLMCallConfig,
    hierarchical_merge,
    load_chunk_cache,
    save_chunk_cache,
)
from summarize.monthly_summary import generate_monthly_markdown
from summarize.weekly_summary import generate_weekly_markdown


def _make_config(prompt_text):
    return LLMCallConfig(prompt=prompt_text, timeout=60)


# ─── Renderers tolerate off-schema shapes ────────────────────────────

def test_monthly_markdown_ai_trends_as_list():
    report = {"summary": "a month",
              "ai_collaboration_trends": ["trend one", "trend two"]}
    md = generate_monthly_markdown(report, 2026, 6)
    assert "trend one" in md and "trend two" in md


def test_monthly_markdown_ai_trends_as_str():
    md = generate_monthly_markdown({"ai_collaboration_trends": "one trend"}, 2026, 6)
    assert "one trend" in md


def test_monthly_markdown_ai_trends_as_dict_still_works():
    report = {"ai_collaboration_trends": {
        "human_initiated_insights": 3,
        "ai_limitation_patterns": ["p1"],
        "improvement_areas": ["a1"]}}
    md = generate_monthly_markdown(report, 2026, 6)
    assert "3 items" in md and "p1" in md and "a1" in md


def test_weekly_markdown_ai_notes_as_list():
    report = {"summary": "a week", "ai_usage_notes": ["note one"]}
    md = generate_weekly_markdown(report, 2026, 23)
    assert "note one" in md


# ─── Parse-failed chunks never poison cache or merge ─────────────────

def test_save_chunk_cache_skips_parse_error(tmp_path):
    save_chunk_cache(tmp_path, "h1", {"parse_error": "x", "raw_response": "junk"},
                     "g1", 2)
    assert not (tmp_path / "h1.json").exists()


def test_load_chunk_cache_rejects_poisoned_entry(tmp_path):
    (tmp_path / "h1.json").write_text(
        '{"parse_error": "x", "raw_response": "junk",'
        ' "_chunk_meta": {"global_hash": "g1", "total_chunks": 2}}',
        encoding="utf-8")
    assert load_chunk_cache(tmp_path, "h1", "g1", 2) is None


def test_hierarchical_merge_drops_parse_failed_chunks():
    good = {"summary": "fine"}
    bad = {"parse_error": "x", "raw_response": "junk " * 10}
    with patch("common.llm.call_llm", return_value={"summary": "merged"}) as mock_call:
        result = hierarchical_merge("ollama", [good, bad, good],
                                    "merge:", _make_config, timeout=60)
    assert result == {"summary": "merged"}
    prompt_sent = mock_call.call_args[0][1].prompt
    assert "junk" not in prompt_sent


def test_hierarchical_merge_all_failed_raises():
    bad = {"parse_error": "x", "raw_response": "junk"}
    with pytest.raises(ValueError):
        hierarchical_merge("ollama", [bad, bad], "merge:", _make_config, timeout=60)


def test_backup_existing_before_overwrite(tmp_path, monkeypatch):
    from summarize import backup
    monkeypatch.setattr(backup, "BACKUP_DIR", tmp_path / "bak")
    f = tmp_path / "2026-06-01.md"
    f.write_text("old", encoding="utf-8")
    saved = backup.backup_existing(f, tmp_path / "missing.json")
    assert len(saved) == 1 and saved[0].read_text(encoding="utf-8") == "old"
    # same mtime -> deduped, no second copy
    assert backup.backup_existing(f) == []
