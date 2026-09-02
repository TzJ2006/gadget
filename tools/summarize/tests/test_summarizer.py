"""Tests for summarize.summarizer — prompt construction, chunking, and tool schema."""

from datetime import date

import pytest

from summarize.summarizer import (
    chunk_conversations,
    format_conversations,
    _build_summary_prompt,
    _daily_tool_schema,
    _normalize_report,
    SUMMARY_PROMPT,
)


def test_normalize_report_fills_summary_from_synonym():
    # known synonyms -> canonical `summary` is populated
    assert _normalize_report({"one_sentence_summary": "did stuff"})["summary"] == "did stuff"
    assert _normalize_report({"daily_summary": "did stuff"})["summary"] == "did stuff"
    # a novel *summary* string key is still recovered (heuristic fallback)
    assert _normalize_report({"session_summary": "did stuff"})["summary"] == "did stuff"
    # an existing summary is never overwritten by a synonym
    assert _normalize_report({"summary": "real", "one_sentence_summary": "alt"})["summary"] == "real"
    # the legit list `conversation_summaries` must NOT be adopted as the summary string
    assert "summary" not in _normalize_report({"conversation_summaries": [{"summary": "x"}]})
    # nothing to fill from -> left as-is (no crash, no empty-string injection)
    assert "summary" not in _normalize_report({"tasks": []})


def test_normalize_report_unwraps_envelope():
    # qwen wraps the whole report in `{id, name, data: {...}}`; unwrap + recover summary
    wrapped = {"id": 10001, "name": "张三",
               "data": {"one_sentence_summary": "did stuff", "tasks": [{"name": "t"}]}}
    out = _normalize_report(wrapped)
    assert out["summary"] == "did stuff"
    assert out["tasks"] == [{"name": "t"}]
    # a top-level report is never unwrapped even if it has a stray dict child
    top = {"summary": "real", "extra": {"tasks": [{"name": "decoy"}]}}
    assert _normalize_report(top)["summary"] == "real"


def test_normalize_report_prefers_renamed_top_over_decoy_child():
    # qwen renamed summary/tasks at the TOP and left a thin `statistics.summary`
    # decoy. Must recover the real top-level summary, NOT unwrap to the decoy.
    r = _normalize_report({
        "one_sentence_summary": "Migrated auth service, fixed 3 bugs",
        "task_list": [{"name": "a"}, {"name": "b"}],
        "statistics": {"summary": "3 tasks"},
    })
    assert r["summary"] == "Migrated auth service, fixed 3 bugs"
    assert "task_list" in r  # the real (renamed) report body is preserved, not dropped


def test_normalize_report_renests_bare_daily_overview():
    # qwen3.8 sometimes answers one level too deep: daily_overview's own contents
    # as the whole report. Re-nest so the overview renders and summary is filled.
    r = _normalize_report({
        "global": {"what": "Cross-device day", "how": "h", "impact": "i"},
        "devices": {"my-pc": {"what": "w", "how": "h", "impact": "i"}},
    })
    assert r["summary"] == "Cross-device day"
    assert r["daily_overview"]["devices"]["my-pc"]["what"] == "w"
    # devices-only (no global) falls back to the first device's `what`
    r2 = _normalize_report({"devices": {"my-pc": {"what": "only device", "how": "h"}}})
    assert r2["summary"] == "only device"
    # a real report that merely CONTAINS daily_overview is left alone
    intact = {"summary": "real", "daily_overview": {"global": {"what": "x"}}}
    assert _normalize_report(intact) == intact


def test_finalize_report_retries_a_structurally_wrong_answer():
    from summarize.summarizer import _finalize_report

    bad = {"global": {"what": "overview only"}, "devices": {}}
    good = {"summary": "real", "tasks": [{"name": "t"}]}

    calls = []

    def flaky():
        calls.append(1)
        return bad if len(calls) == 1 else good

    assert _finalize_report(flaky) == good
    assert len(calls) == 2

    # a good first answer is never re-rolled (a retry would cost a whole merge call)
    calls.clear()
    assert _finalize_report(lambda: calls.append(1) or good) == good
    assert len(calls) == 1

    # both attempts wrong -> salvaged, not blank, and no third call
    calls.clear()
    out = _finalize_report(lambda: calls.append(1) or dict(bad))
    assert len(calls) == 2
    assert out["summary"] == "overview only"


def test_normalize_report_unwraps_to_richest_child():
    # pure wrapper whose real report sits under a non-envelope key alongside a decoy
    r = _normalize_report({
        "id": 1,
        "statistics": {"summary": "3 tasks"},                     # thin decoy (score 1)
        "body": {"one_sentence_summary": "real", "tasks": [{"name": "t"}]},  # score 2
    })
    assert r["summary"] == "real" and r["tasks"] == [{"name": "t"}]


# ── Helpers ───────────────────────────────────────────────────────────


def _make_conversation(project: str, msg_count: int = 3, msg_len: int = 100) -> dict:
    """Build a synthetic conversation dict with controllable size."""
    messages = [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"msg{'x' * msg_len}"}
        for i in range(msg_count)
    ]
    return {
        "source": "claude_code",
        "project": project,
        "timestamp": "2026-03-20T10:00:00+00:00",
        "messages": messages,
    }


# ── chunk_conversations ──────────────────────────────────────────────


def test_chunk_conversations_small():
    """Conversations under the limit stay in a single chunk."""
    convs = [_make_conversation("proj-a"), _make_conversation("proj-b")]
    chunks = chunk_conversations(convs, max_chars=500_000)

    assert len(chunks) == 1
    assert len(chunks[0]) == 2


def test_chunk_conversations_large():
    """Conversations exceeding the limit are split across chunks."""
    # Each conversation ~3000 chars; set limit low to force splitting
    convs = [_make_conversation(f"proj-{i}", msg_count=10, msg_len=200) for i in range(5)]
    chunks = chunk_conversations(convs, max_chars=3000)

    assert len(chunks) > 1
    # All conversations accounted for
    total = sum(len(c) for c in chunks)
    assert total == 5


# ── format_conversations ─────────────────────────────────────────────


def test_format_conversations():
    """Formats a list of conversation dicts into a readable text block."""
    convs = [
        {
            "source": "claude_code",
            "project": "gadget",
            "timestamp": "2026-03-20T10:00:00+00:00",
            "messages": [
                {"role": "user", "content": "What is this project?"},
                {"role": "assistant", "content": "A Python toolkit."},
            ],
        },
    ]

    text = format_conversations(convs)

    assert "gadget" in text
    assert "What is this project?" in text
    assert "A Python toolkit." in text
    assert "claude_code" in text


# ── _build_summary_prompt ────────────────────────────────────────────


def test_build_summary_prompt():
    """Returns a non-empty string prompt containing the schema description."""
    prompt = _build_summary_prompt()

    assert isinstance(prompt, str)
    assert len(prompt) > 100
    assert "daily_overview" in prompt
    # Single-device prompt should use the flat format
    assert "what" in prompt


def test_build_summary_prompt_multi_device():
    """Multi-device prompt includes device-specific overview structure."""
    prompt = _build_summary_prompt(device_labels=["desktop", "laptop"])

    assert "desktop" in prompt
    assert "laptop" in prompt
    assert "global" in prompt


# ── _daily_tool_schema ────────────────────────────────────────────────


def test_daily_tool_schema():
    """Returns a valid list containing one tool schema dict."""
    schema = _daily_tool_schema()

    assert isinstance(schema, list)
    assert len(schema) == 1

    tool = schema[0]
    assert tool["name"] == "submit_report"
    assert "input_schema" in tool

    props = tool["input_schema"]["properties"]
    assert "date" in props
    assert "summary" in props
    assert "tasks" in props
    assert "conversation_summaries" in props

    required = tool["input_schema"]["required"]
    assert "date" in required
    assert "summary" in required
    assert "tasks" in required
