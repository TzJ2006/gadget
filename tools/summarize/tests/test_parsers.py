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
    monkeypatch.setattr("summarize.parsers._DAY_INDEX_PATH", tmp_path / "day_index.json")
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


def test_parse_cursor_undated_is_not_assigned_file_date(fake_home):
    """File modification time is not a message date; exclude undated messages."""
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
    assert result == []
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
        "message": {"role": "user", "content": "claude hello, please refactor the research module into a package and add tests for it"},
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
                    "text": f"{ts_tag}<user_query>cursor hello, please refactor the research module into a package and add tests for it</user_query>",
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


# ── parse_gemini / parse_antigravity ───────────────────────────────────


def test_parse_gemini_json_and_jsonl(fake_home):
    """Old single-JSON sessions and newer JSONL sessions both parse; .project_root names the project."""
    from summarize.parsers import parse_gemini

    stamp = "2026-07-14T16:00:00Z"
    target = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone().date()
    proj = fake_home / ".gemini" / "tmp" / "abc123"
    (proj / "chats").mkdir(parents=True)
    (proj / ".project_root").write_text(r"c:\work\MyProj", encoding="utf-8")
    (proj / "chats" / "session-old.json").write_text(json.dumps({
        "sessionId": "s-old",
        "messages": [
            {"id": "1", "timestamp": stamp, "type": "user", "content": "hi gemini"},
            {"id": "2", "timestamp": stamp, "type": "gemini", "content": [{"text": "hello"}]},
            {"id": "3", "timestamp": stamp, "type": "info", "content": "ignored"},
        ],
    }), encoding="utf-8")
    (proj / "chats" / "session-new.jsonl").write_text("".join(json.dumps(o) + "\n" for o in [
        {"sessionId": "s-new", "startTime": stamp},
        {"id": "1", "timestamp": stamp, "type": "user", "content": "q"},
        {"id": "2", "timestamp": stamp, "type": "gemini", "content": "draft"},
        {"id": "2", "timestamp": stamp, "type": "gemini", "content": "final"},
    ]), encoding="utf-8")

    result = {c["conversation_id"]: c for c in parse_gemini(target)}
    assert set(result) == {"s-old", "s-new"}
    assert result["s-old"]["source"] == "gemini"
    assert result["s-old"]["project"] == "MyProj"
    assert [m["content"] for m in result["s-old"]["messages"]] == ["hi gemini", "hello"]
    assert [m["content"] for m in result["s-new"]["messages"]] == ["q", "final"]
    assert parse_gemini(date(2020, 1, 1)) == []


def test_parse_antigravity_keeps_dialogue_skips_subagents(fake_home):
    """User requests are unwrapped, tool/system steps dropped, user-less (subagent) logs skipped."""
    from summarize.parsers import parse_antigravity

    stamp = "2026-07-14T16:00:00Z"
    target = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone().date()
    brain = fake_home / ".gemini" / "antigravity" / "brain"

    def write(conv_id, steps):
        logs = brain / conv_id / ".system_generated" / "logs"
        logs.mkdir(parents=True)
        (logs / "transcript_full.jsonl").write_text(
            "".join(json.dumps({"step_index": i, "created_at": stamp, **s}) + "\n" for i, s in enumerate(steps)),
            encoding="utf-8")

    write("parent", [
        {"type": "USER_INPUT", "content": "<USER_REQUEST>\nfix it\n</USER_REQUEST>\n<ADDITIONAL_METADATA>x</ADDITIONAL_METADATA>"},
        {"type": "PLANNER_RESPONSE", "tool_calls": [{"name": "grep"}]},
        {"type": "GENERIC", "content": "tool output"},
        {"type": "SYSTEM_MESSAGE", "content": "system"},
        {"type": "PLANNER_RESPONSE", "content": "done"},
    ])
    write("subagent", [{"type": "PLANNER_RESPONSE", "content": "reported to parent"}])

    import sqlite3
    db = sqlite3.connect(brain.parent / "conversation_summaries.db")
    db.execute("create table conversation_summaries (conversation_id text, workspace_uris text)")
    db.execute("insert into conversation_summaries values ('parent', ?)",
               (json.dumps(["file:///c%3A/Users/me/My%20Proj"]),))
    db.commit()
    db.close()

    result = parse_antigravity(target)
    assert len(result) == 1
    conv = result[0]
    assert (conv["source"], conv["conversation_id"], conv["project"]) == ("antigravity", "parent", "My Proj")
    assert conv["messages"] == [{"role": "user", "content": "fix it"}, {"role": "assistant", "content": "done"}]
    assert target in discover_all_dates()


def test_parse_antigravity_falls_back_to_search_index(fake_home):
    """A conversation with no step log is rebuilt from the FTS index, split at byte offsets."""
    import sqlite3
    from summarize.parsers import parse_antigravity

    root = fake_home / ".gemini" / "antigravity"
    (root / "brain").mkdir(parents=True)
    when = datetime(2026, 3, 29, 16, 0).astimezone()
    user, agent = "你好\nsecond ask", "\nfirst answer\nsecond answer"
    db = sqlite3.connect(root / "conversation_summaries.db")
    try:
        db.execute("create virtual table conversations_fts using fts5(conversation_id, chunk_index,"
                   " last_step_created_at, workspace, user_step_byte_offsets, user_body,"
                   " agent_step_byte_offsets, agent_body)")
    except sqlite3.OperationalError:
        pytest.skip("sqlite built without FTS5")
    db.execute("insert into conversations_fts values ('old', -1, ?, 'Proj', '', '', '', '')",
               (int(when.timestamp() * 1e9),))
    db.execute("insert into conversations_fts values ('old', 0, 0, '', ?, ?, ?, ?)",
               (json.dumps([[0, 0], [5, 7]]), user, json.dumps([[2, 0], [4, 1], [7, 14]]), agent))
    db.execute("insert into conversations_fts values ('sub', 0, 0, '', '[]', '', '[[1,0]]', 'no user turn')")
    db.commit()
    db.close()

    result = parse_antigravity(when.date())
    assert len(result) == 1
    assert (result[0]["conversation_id"], result[0]["project"]) == ("old", "Proj")
    assert result[0]["messages"] == [
        {"role": "user", "content": "你好"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second ask"},
        {"role": "assistant", "content": "second answer"},
    ]
    assert parse_antigravity(date(2020, 1, 1)) == []


def test_drop_probes_removes_health_check_pings():
    from summarize.parsers import drop_probes, is_probe
    probe = {"messages": [{"role": "user", "content": "Respond with OK only."},
                          {"role": "assistant", "content": "OK"}]}
    real_short = {"messages": [{"role": "user", "content": "fix it"}, {"role": "assistant", "content": "done"},
                               {"role": "user", "content": "thanks"}]}
    real_long = {"messages": [{"role": "user", "content": "Refactor research_scout.py into a scout/ package " * 3}]}
    assert is_probe(probe)
    assert not is_probe(real_short) and not is_probe(real_long)
    assert drop_probes([probe, real_short, real_long]) == [real_short, real_long]
