"""Conversation parsing utilities for multiple AI assistant log formats.

Parsers for Claude Code, Codex, Cursor Agent, ChatGPT export, and generic JSON
conversation formats. Each parser returns a list of unified conversation dicts.
"""

import json
import os
import platform
import re
import sys
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from typing import Optional

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


def _iter_cursor_parent_jsonl(root):
    from .discovery import iter_cursor_parent_jsonl
    for path in iter_cursor_parent_jsonl(root):
        yield root.parent.name, path


from .records import _cursor_timestamp as _parse_cursor_timestamp


from .records import _cursor_text as _cursor_message_text


# ─── 统一对话格式 ───────────────────────────────────────────────

# 每个 conversation 结构:
# {
#     "source": "claude_code" | "codex" | "cursor" | "chatgpt" | "generic",
#     "project": "project_name",
#     "timestamp": "ISO8601",
#     "messages": [{"role": "user"|"assistant", "content": "..."}]
# }


from .records import _extract_blocks as _extract_text_content


def discover_all_dates():
    from .records import load_records, _local_day
    dates = set()
    for kind, roots in [("claude_code", _discover_claude_project_dirs()),
                        ("codex", _discover_codex_session_dirs()),
                        ("cursor", _discover_cursor_transcript_roots())]:
        for root in roots:
            try:
                rows, _ = load_records(kind, root)
            except ValueError:
                continue
            dates.update(day for row in rows if (day := _local_day(row["ts"])))
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

    return all_conversations


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
