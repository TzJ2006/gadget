"""Tests for summarize.parsers — conversation parsing from multiple sources."""

import json
import os
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from summarize.parsers import (
    _discover_claude_project_dirs,
    _parse_cursor_timestamp,
    discover_all_dates,
    parse_claude_code,
    parse_chatgpt_export,
    parse_cursor,
    parse_generic,
    collect_conversations,
)


def _write_cursor_parent(fake_home: Path, project: str, lines: list[dict],
                         conv_id: str | None = None) -> Path:
    """Write a parent Cursor agent transcript under fake_home."""
    conv_id = conv_id or str(uuid4())
    conv_dir = (
        fake_home / ".cursor" / "projects" / project / "agent-transcripts" / conv_id
    )
    conv_dir.mkdir(parents=True)
    path = conv_dir / f"{conv_id}.jsonl"
    path.write_text(
        "".join(json.dumps(obj) + "\n" for obj in lines), encoding="utf-8"
    )
    return path


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


# ── parse_cursor ───────────────────────────────────────────────────────


def test_parse_cursor_no_dir(fake_home):
    """When no ~/.cursor/projects exist, returns empty list."""
    assert parse_cursor(date(2026, 1, 1)) == []


def test_parse_cursor_timestamp_and_strips_wrappers(fake_home):
    """Parent JSONL with <timestamp> exports; user_query / timestamp tags stripped."""
    ts_tag = "<timestamp>Tuesday, Jul 14, 2026, 5:16 PM (UTC-4)</timestamp>"
    target = _parse_cursor_timestamp(ts_tag).astimezone().date()
    _write_cursor_parent(
        fake_home,
        "d-GitHub-gadget",
        [
            {
                "role": "user",
                "message": {
                    "content": [{
                        "type": "text",
                        "text": f"{ts_tag}\n<user_query>\nhello cursor\n</user_query>",
                    }],
                },
            },
            {
                "role": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "hi there"},
                        {"type": "tool_use", "name": "Read", "input": {"path": "x"}},
                    ],
                },
            },
            {"type": "turn_ended", "status": "success"},
        ],
    )

    result = parse_cursor(target)
    assert len(result) == 1
    conv = result[0]
    assert conv["source"] == "cursor"
    assert conv["project"] == "d-GitHub-gadget"
    assert len(conv["messages"]) == 2
    assert conv["messages"][0]["role"] == "user"
    assert conv["messages"][0]["content"] == "hello cursor"
    assert "<timestamp>" not in conv["messages"][0]["content"]
    assert conv["messages"][1]["content"] == "hi there"


def test_parse_cursor_skips_subagents(fake_home):
    """subagents/*.jsonl must not be exported."""
    ts_tag = "<timestamp>Monday, Jul 13, 2026, 12:00 PM (UTC+0)</timestamp>"
    target = _parse_cursor_timestamp(ts_tag).astimezone().date()
    conv_id = str(uuid4())
    parent = _write_cursor_parent(
        fake_home,
        "proj",
        [{
            "role": "user",
            "message": {
                "content": [{"type": "text", "text": f"{ts_tag}<user_query>parent</user_query>"}],
            },
        }],
        conv_id=conv_id,
    )
    sub_dir = parent.parent / "subagents"
    sub_dir.mkdir()
    sub_id = str(uuid4())
    (sub_dir / f"{sub_id}.jsonl").write_text(
        json.dumps({
            "role": "user",
            "message": {
                "content": [{"type": "text", "text": f"{ts_tag}<user_query>sub</user_query>"}],
            },
        }) + "\n",
        encoding="utf-8",
    )

    result = parse_cursor(target)
    assert len(result) == 1
    assert result[0]["messages"][0]["content"] == "parent"


def test_parse_cursor_mtime_fallback(fake_home):
    """No <timestamp> tags → include conversation when file mtime matches target day."""
    target = date(2026, 3, 15)
    path = _write_cursor_parent(
        fake_home,
        "mtime-proj",
        [
            {
                "role": "user",
                "message": {"content": [{"type": "text", "text": "no stamp"}]},
            },
            {
                "role": "assistant",
                "message": {"content": [{"type": "text", "text": "ok"}]},
            },
        ],
    )
    epoch = datetime(2026, 3, 15, 12, 0, 0).timestamp()
    os.utime(path, (epoch, epoch))

    result = parse_cursor(target)
    assert len(result) == 1
    assert result[0]["source"] == "cursor"
    assert result[0]["project"] == "mtime-proj"
    assert parse_cursor(date(2026, 3, 16)) == []


def test_discover_all_dates_includes_cursor(fake_home):
    """discover_all_dates picks up Cursor parent transcript dates."""
    ts_tag = "<timestamp>Wednesday, Jul 15, 2026, 10:00 AM (UTC+0)</timestamp>"
    expected = _parse_cursor_timestamp(ts_tag).astimezone().date()
    _write_cursor_parent(
        fake_home,
        "proj",
        [{
            "role": "user",
            "message": {
                "content": [{"type": "text", "text": f"{ts_tag}<user_query>x</user_query>"}],
            },
        }],
    )
    assert expected in discover_all_dates()


def test_collect_conversations_claude_and_cursor(fake_home):
    """collect_conversations returns both Claude Code and Cursor sessions."""
    # Same UTC instant for both parsers so local calendar day matches.
    ts_tag = "<timestamp>Monday, Apr 20, 2026, 12:00 PM (UTC+0)</timestamp>"
    target = _parse_cursor_timestamp(ts_tag).astimezone().date()

    claude_msg = {
        "type": "user",
        "timestamp": "2026-04-20T12:00:00Z",
        "message": {"role": "user", "content": "claude hello"},
    }
    proj = fake_home / ".claude" / "projects" / "test-proj"
    proj.mkdir(parents=True)
    (proj / "session.jsonl").write_text(
        json.dumps(claude_msg) + "\n", encoding="utf-8"
    )

    _write_cursor_parent(
        fake_home,
        "cursor-proj",
        [{
            "role": "user",
            "message": {
                "content": [{
                    "type": "text",
                    "text": f"{ts_tag}<user_query>cursor hello</user_query>",
                }],
            },
        }],
    )

    result = collect_conversations(target)
    sources = {c["source"] for c in result}
    assert "claude_code" in sources
    assert "cursor" in sources


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


def test_parse_cursor_timestamp_utc_offset():
    """UTC±N offsets in Cursor timestamp tags parse to aware datetimes."""
    dt = _parse_cursor_timestamp(
        "<timestamp>Tuesday, Jul 14, 2026, 5:16 PM (UTC-4)</timestamp>"
    )
    assert dt is not None
    assert dt.year == 2026 and dt.month == 7 and dt.day == 14
    assert dt.hour == 17 and dt.minute == 16
    assert dt.utcoffset().total_seconds() == -4 * 3600
