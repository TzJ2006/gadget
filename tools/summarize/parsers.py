"""Conversation parsing utilities for multiple AI assistant log formats.

Parsers for Claude Code, Codex, Cursor Agent, ChatGPT export, and generic JSON
conversation formats. Each parser returns a list of unified conversation dicts.
"""

import json
import os
import platform
import re
import sys
import time
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Optional

from common.io import atomic_write as _atomic_write
from common.paths import CACHE_DIR

from .config import _load_config


# Cursor Agent user text embeds: <timestamp>Tuesday, Jul 14, 2026, 5:16 PM (UTC-4)</timestamp>
_CURSOR_TS_TAG_RE = re.compile(
    r"<timestamp>\s*(.*?)\s*</timestamp>", re.IGNORECASE | re.DOTALL)
_CURSOR_TS_BODY_RE = re.compile(
    r"^(.*?)\s*\(\s*UTC\s*([+-]\d{1,2})(?::?(\d{2}))?\s*\)\s*$",
    re.IGNORECASE | re.DOTALL)
_CURSOR_USER_QUERY_RE = re.compile(
    r"<user_query>\s*(.*?)\s*</user_query>", re.IGNORECASE | re.DOTALL)


from .discovery import _is_dir


def _home_dirs():
    from .discovery import home_dirs
    return home_dirs()


def _discover_claude_project_dirs():
    from .discovery import claude_project_dirs
    return claude_project_dirs(_home_dirs())


def _discover_codex_session_dirs():
    from .discovery import codex_session_dirs
    return codex_session_dirs(_home_dirs())


def _discover_cursor_transcript_roots():
    from .discovery import cursor_transcript_roots
    return cursor_transcript_roots(_home_dirs())


def _discover_gemini_chat_dirs():
    from .discovery import gemini_chat_dirs
    return gemini_chat_dirs(_home_dirs())


def _discover_antigravity_brain_dirs():
    from .discovery import antigravity_brain_dirs
    return antigravity_brain_dirs(_home_dirs())


def _iter_cursor_parent_jsonl(root):
    from .discovery import iter_cursor_parent_jsonl
    for path in iter_cursor_parent_jsonl(root):
        yield root.parent.name, path


from .records import _cursor_timestamp as _parse_cursor_timestamp


from .records import _cursor_text as _cursor_message_text


# ─── 统一对话格式 ───────────────────────────────────────────────

# 每个 conversation 结构:
# {
#     "source": "claude_code" | "codex" | "cursor" | "gemini" | "antigravity" | "chatgpt" | "generic",
#     "project": "project_name",
#     "timestamp": "ISO8601",
#     "messages": [{"role": "user"|"assistant", "content": "..."}]
# }


from .records import _extract_blocks as _extract_text_content


_DAY_INDEX_PATH = CACHE_DIR / "summarize" / "day_index.json"
_DAY_INDEXED_KINDS = ("claude_code", "codex")


def _tz_identity():
    # _local_day uses astimezone(), so any timezone change invalidates every cached day set.
    offset = datetime.now().astimezone().utcoffset()
    return [list(time.tzname), time.timezone, time.altzone, offset.total_seconds() if offset else 0]


def _load_day_index() -> dict:
    try:
        data = json.loads(_DAY_INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict) or data.get("tz") != _tz_identity() or not isinstance(data.get("files"), dict):
        return {}
    return data["files"]


def _indexed_root_days(kind, root, cached, fresh):
    """Per-file day sets for one root, reusing entries whose size and mtime_ns match."""
    from .records import load_records, _local_day, _files_for
    if not Path(root).exists():
        raise ValueError(f"path does not exist: {root}")
    days = set()
    for file in _files_for(kind, Path(root)):
        try:
            st = file.stat()
        except OSError as exc:
            raise ValueError(f"cannot read {file}: {exc}") from exc
        key = str(file)
        entry = cached.get(key)
        if not (isinstance(entry, dict) and entry.get("size") == st.st_size
                and entry.get("mtime_ns") == st.st_mtime_ns):
            rows, _ = load_records(kind, file)
            entry = {"size": st.st_size, "mtime_ns": st.st_mtime_ns,
                     "days": sorted({day.isoformat() for row in rows if (day := _local_day(row["ts"]))})}
        fresh[key] = entry
        days.update(date.fromisoformat(item) for item in entry["days"])
    return days


def discover_all_dates():
    from .records import load_records, _local_day
    cached = _load_day_index()
    fresh = {}
    dates = set()
    for kind, roots in [("claude_code", _discover_claude_project_dirs()),
                        ("codex", _discover_codex_session_dirs()),
                        ("cursor", _discover_cursor_transcript_roots()),
                        ("gemini", _discover_gemini_chat_dirs()),
                        ("antigravity", _discover_antigravity_brain_dirs())]:
        for root in roots:
            if kind in _DAY_INDEXED_KINDS:
                try:
                    dates.update(_indexed_root_days(kind, root, cached, fresh))
                except ValueError:
                    continue
                continue
            try:
                rows, _ = load_records(kind, root)
            except ValueError:
                continue
            dates.update(day for row in rows if (day := _local_day(row["ts"])))
    if fresh != cached:
        try:
            _atomic_write(_DAY_INDEX_PATH, json.dumps({"tz": _tz_identity(), "files": fresh}))
        except OSError:
            pass
    return dates


def parse_claude_code(target_date):
    return _from_paths("claude_code", _discover_claude_project_dirs(), target_date)


def parse_chatgpt_export(filepath, target_date):
    return _from_paths("chatgpt", [Path(filepath)], target_date)


def parse_generic(filepath: str, target_date: date) -> list[dict]:
    """解析通用 JSON 对话格式：[{"role": "user/assistant", "content": "..."}]"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[error] 读取通用格式文件失败: {e}")
        return []

    if not isinstance(data, list):
        print(f"[error] 通用格式应为 JSON 数组")
        return []

    messages = []
    for item in data:
        role = item.get("role", "")
        content = item.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": str(content)})

    if messages:
        return [{
            "source": "generic",
            "project": Path(filepath).stem,
            "timestamp": target_date.isoformat(),
            "messages": messages,
        }]
    return []


from .records import _extract_blocks as _extract_codex_text


from .records import _extract_codex_project


def parse_codex(target_date):
    return _from_paths("codex", _discover_codex_session_dirs(), target_date)


def parse_cursor(target_date):
    result = []
    for root in _discover_cursor_transcript_roots():
        for project, file in _iter_cursor_parent_jsonl(root):
            result.extend(_from_paths("cursor", [file], target_date, project=project))
    return result


def parse_gemini(target_date):
    return _from_paths("gemini", _discover_gemini_chat_dirs(), target_date)


def parse_antigravity(target_date):
    return _from_paths("antigravity", _discover_antigravity_brain_dirs(), target_date)


def collect_conversations(target_date: date, chatgpt: Optional[str] = None,
                          generic: Optional[list[str]] = None) -> list[dict]:
    """从本地各来源收集对话记录。"""
    all_conversations = []

    # 1. Claude Code 对话（默认扫描）
    print("[info] 扫描 Claude Code 对话记录...")
    claude_convs = parse_claude_code(target_date)
    print(f"[info] 找到 {len(claude_convs)} 个 Claude Code 会话")
    all_conversations.extend(claude_convs)

    # 2. Codex 对话（默认扫描）
    print("[info] 扫描 Codex 对话记录...")
    codex_convs = parse_codex(target_date)
    print(f"[info] 找到 {len(codex_convs)} 个 Codex 会话")
    all_conversations.extend(codex_convs)

    # 3. Cursor Agent 对话（默认扫描；无 token usage）
    print("[info] 扫描 Cursor Agent 对话记录...")
    cursor_convs = parse_cursor(target_date)
    print(f"[info] 找到 {len(cursor_convs)} 个 Cursor 会话")
    all_conversations.extend(cursor_convs)

    # Gemini CLI / Antigravity（默认扫描；无 token usage）
    for label, parse in (("Gemini CLI", parse_gemini), ("Antigravity", parse_antigravity)):
        print(f"[info] 扫描 {label} 对话记录...")
        convs = parse(target_date)
        print(f"[info] 找到 {len(convs)} 个 {label} 会话")
        all_conversations.extend(convs)

    # 4. ChatGPT 导出
    if chatgpt:
        print(f"[info] 解析 ChatGPT 导出: {chatgpt}")
        chatgpt_convs = parse_chatgpt_export(chatgpt, target_date)
        print(f"[info] 找到 {len(chatgpt_convs)} 个 ChatGPT 会话")
        all_conversations.extend(chatgpt_convs)

    # 5. 通用格式
    for gpath in (generic or []):
        print(f"[info] 解析通用格式: {gpath}")
        generic_convs = parse_generic(gpath, target_date)
        print(f"[info] 找到 {len(generic_convs)} 个通用格式会话")
        all_conversations.extend(generic_convs)

    return drop_probes(all_conversations)


def is_probe(conv: dict) -> bool:
    """A health-check ping, not work: one user message and almost no text.

    TokenMonitor fires ~140 "Respond with OK only." sessions a day; they bloat
    session counts and crowd a whole chunk.
    # ponytail: size-only rule; a real one-line question under 80 chars total
    #           is dropped too — add a prompt allowlist if that ever matters.
    """
    msgs = conv.get("messages") or []
    users = [m for m in msgs if m.get("role") == "user"]
    return len(users) <= 1 and sum(len(str(m.get("content", ""))) for m in msgs) < 80


def drop_probes(conversations: list[dict]) -> list[dict]:
    kept = [c for c in conversations if not is_probe(c)]
    if len(kept) < len(conversations):
        print(f"[info] 过滤 {len(conversations) - len(kept)} 个探测会话（单条极短消息）")
    return kept


def _from_paths(kind, paths, target_date, project=None):
    """Legacy CLI shape over the same record parser used by PersonalAgents."""
    from .records import load_records
    result = []
    for path in paths:
        try:
            rows, _ = load_records(kind, path, on_date=target_date)
        except ValueError:
            continue
        groups = {}
        for row in rows:
            key = row["conversation_id"]
            group = groups.setdefault(key, {"source": kind, "project": project or row.get("project") or key,
                "timestamp": row["ts"], "conversation_id": key, "messages": []})
            group["messages"].append({"role": row["role"], "content": row["text"]})
        result.extend(groups.values())
    return result
