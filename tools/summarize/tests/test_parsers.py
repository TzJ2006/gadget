"""Tests for summarize.parsers — conversation parsing from multiple sources."""

import json
from datetime import date
from pathlib import Path

import pytest

from summarize.parsers import (
    _discover_claude_project_dirs,
    discover_all_dates,
    parse_claude_code,
    parse_chatgpt_export,
    parse_generic,
    collect_conversations,
)


@pytest.fixture()
def fake_home(tmp_path, monkeypatch):
    """Redirect Path.home() to a temporary directory."""
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    return tmp_path


# ── parse_claude_code ─────────────────────────────────────────────────


def test_parse_claude_code_no_dir(fake_home):
    """When no ~/.claude*/projects exist, returns empty list."""
    result = parse_claude_code(date(2026, 1, 1))
    assert result == []


def test_discover_claude_project_dirs_multiple(fake_home):
    """Discovers both ~/.claude/projects and ~/.claude-code/projects."""
    (fake_home / ".claude" / "projects").mkdir(parents=True)
    (fake_home / ".claude-code" / "projects").mkdir(parents=True)
    (fake_home / ".claude-unrelated").mkdir()  # no projects/ subdir

    dirs = _discover_claude_project_dirs()
    names = {d.parent.name for d in dirs}
    assert ".claude" in names
    assert ".claude-code" in names
    assert ".claude-unrelated" not in names


def test_parse_claude_code_multi_dir(fake_home):
    """Conversations from both ~/.claude and ~/.claude-code are collected."""
    target = date(2026, 4, 20)
    msg = {
        "type": "user",
        "timestamp": "2026-04-20T10:00:00Z",
        "message": {"role": "user", "content": "hello"},
    }

    for dirname in (".claude", ".claude-code"):
        proj = fake_home / dirname / "projects" / "test-proj"
        proj.mkdir(parents=True)
        (proj / "session.jsonl").write_text(
            json.dumps(msg) + "\n", encoding="utf-8"
        )

    result = parse_claude_code(target)
    assert len(result) == 2


# ── parse_chatgpt_export ──────────────────────────────────────────────


def test_parse_chatgpt_export_invalid_file():
    """Invalid file path returns empty list."""
    result = parse_chatgpt_export("/no/such/file.json", date(2026, 1, 1))
    assert result == []


# ── parse_generic ─────────────────────────────────────────────────────


def test_parse_generic_invalid_file():
    """Invalid file path returns empty list."""
    result = parse_generic("/no/such/file.json", date(2026, 1, 1))
    assert result == []


def test_parse_generic_valid_file(tmp_path):
    """A valid generic JSON file produces one conversation dict."""
    data = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]
    filepath = tmp_path / "chat.json"
    filepath.write_text(json.dumps(data), encoding="utf-8")

    result = parse_generic(str(filepath), date(2026, 3, 20))
    assert len(result) == 1
    assert result[0]["source"] == "generic"
    assert result[0]["project"] == "chat"
    assert len(result[0]["messages"]) == 2


# ── collect_conversations ─────────────────────────────────────────────


def test_collect_conversations_empty(fake_home):
    """When no sources have data, returns empty list."""
    result = collect_conversations(date(2026, 1, 1))
    assert result == []


# ── discover_all_dates ────────────────────────────────────────────────


def test_discover_all_dates_no_dirs(fake_home):
    """When neither ~/.claude/projects nor ~/.codex/sessions exist, returns empty set."""
    result = discover_all_dates()
    assert result == set()
