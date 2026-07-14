"""Tests for summarize.formatter — report rendering and sorting utilities."""

from datetime import date

import pytest

from summarize.formatter import (
    _importance_sort_key,
    _sort_report_by_importance,
    _coerce_report_lists,
    _has_level_metadata,
    _split_by_level,
    generate_markdown,
)


def test_generate_markdown_tolerates_bare_string_list_items():
    """qwen sometimes emits list items as bare strings; render must not crash."""
    report = {
        "summary": "s",
        "tasks": ["did a thing", {"name": "real", "status": "completed"}],
        "problems_and_solutions": ["a problem"],
        "human_vs_ai": ["a topic"],
        "conversation_summaries": ["a bare conversation summary"],
        "learnings": ["a learning"],
    }
    md = generate_markdown(report, date(2026, 6, 26))   # must not raise
    assert "did a thing" in md and "a bare conversation summary" in md


def test_coerce_report_lists_wraps_and_drops():
    r = _coerce_report_lists({
        "tasks": ["str-task", {"name": "dict-task"}, 42, "", None],
        "conversation_summaries": ["c"],
    })
    assert r["tasks"] == [{"name": "str-task"}, {"name": "dict-task"}]   # junk dropped
    assert r["conversation_summaries"] == [{"summary": "c"}]


# ── _importance_sort_key ──────────────────────────────────────────────


def test_importance_sort_key():
    """High-level items sort before low-level; higher importance first within level."""
    high_8 = {"level": "high", "importance": 8}
    high_5 = {"level": "high", "importance": 5}
    low_9 = {"level": "low", "importance": 9}
    low_3 = {"level": "low", "importance": 3}
    no_level = {"importance": 4}
    plain_str = "just a string"

    items = [low_3, plain_str, no_level, high_5, low_9, high_8]
    sorted_items = sorted(items, key=_importance_sort_key)

    # Expected order: high_8, high_5, low_9, low_3, no_level, plain_str
    assert sorted_items == [high_8, high_5, low_9, low_3, no_level, plain_str]


# ── _sort_report_by_importance ────────────────────────────────────────


def test_sort_report_by_importance():
    """Full report sorting puts high-importance items first in each section."""
    report = {
        "tasks": [
            {"name": "bugfix", "level": "low", "importance": 3},
            {"name": "architecture", "level": "high", "importance": 9},
        ],
        "learnings": [
            {"content": "minor", "level": "low", "importance": 2},
            {"content": "major", "level": "high", "importance": 8},
        ],
    }

    result = _sort_report_by_importance(report)

    assert result["tasks"][0]["name"] == "architecture"
    assert result["tasks"][1]["name"] == "bugfix"
    assert result["learnings"][0]["content"] == "major"
    assert result["learnings"][1]["content"] == "minor"


# ── _has_level_metadata ──────────────────────────────────────────────


def test_has_level_metadata_true():
    """Items with a valid level field return True."""
    items = [
        {"content": "a", "level": "high", "importance": 5},
        {"content": "b"},
    ]
    assert _has_level_metadata(items) is True


def test_has_level_metadata_false():
    """Items without any level field return False."""
    items = [
        {"content": "a", "importance": 5},
        {"content": "b"},
    ]
    assert _has_level_metadata(items) is False


# ── _split_by_level ──────────────────────────────────────────────────


def test_split_by_level():
    """Correctly partitions items into high and low buckets."""
    items = [
        {"content": "a", "level": "high", "importance": 9},
        {"content": "b", "level": "low", "importance": 3},
        {"content": "c"},  # no level → goes to low
        {"content": "d", "level": "high", "importance": 7},
    ]

    high, low = _split_by_level(items)

    assert len(high) == 2
    assert all(h["level"] == "high" for h in high)
    assert len(low) == 2
    assert low[0]["content"] == "b"
    assert low[1]["content"] == "c"


# ── generate_markdown ────────────────────────────────────────────────


def test_generate_markdown_basic():
    """Generate markdown from a minimal report dict produces expected sections."""
    report = {
        "summary": "Productive day on the project.",
        "daily_overview": {
            "what": "Refactored config module",
            "how": "Extracted into standalone file with tests",
            "impact": "Cleaner architecture, easier testing",
        },
        "tasks": [
            {
                "name": "Config refactor",
                "status": "completed",
                "description": "Split config into its own module",
                "level": "high",
                "importance": 8,
            },
        ],
        "conversation_summaries": [
            {
                "project": "gadget",
                "source": "claude_code",
                "timestamp": "2026-03-20T10:00:00+00:00",
                "topic": "Config module extraction",
                "summary": "Extracted config loading into summarize/config.py.",
                "outcome": "completed",
                "level": "high",
                "importance": 8,
            },
        ],
    }

    md = generate_markdown(report, date(2026, 3, 20))

    assert "# Daily Report — 2026-03-20" in md
    assert "Productive day on the project." in md
    assert "Refactored config module" in md
    assert "Config refactor" in md
    assert "Config module extraction" in md


def test_markdown_lists_all_sources():
    report = {
        "summary": "s", "daily_overview": "", "tasks": [],
        "token_usage_by_source": {
            "claude_code": {"totals": {"totalCost": 1.0, "totalTokens": 1_000_000}},
            "gemini": {"totals": {"totalCost": 0.5, "totalTokens": 2_000_000}},
        },
    }
    md = generate_markdown(report, date(2026, 6, 14))
    assert "## Token Usage" in md
    assert 'class="usage-card"' in md   # embedded HTML card
    assert "$1.50" in md                # combined total cost
    assert ">3M<" in md                 # combined total tokens stat
    assert "Claude Code $1" in md       # cost-split legend lists sources
    assert "Gemini $0" in md
