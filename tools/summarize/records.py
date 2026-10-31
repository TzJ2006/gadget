"""Import AI chat exports and local CLI logs into the texts table.

Canonical parsers for ChatGPT current branch,
Claude Code JSONL, Codex session JSONL, and Cursor agent transcripts.
Nothing here scans a home directory. The caller passes a file or a directory.

Cursor often stamps only the user turn. Assistant answers with no timestamp
stay with that turn for date filtering, but the inferred day is not stored as
their ts. An answer that has its own timestamp uses that local date and does
not move the turn date. The next user turn replaces the turn date; a user turn
with no timestamp clears it, so later answers are not kept on the previous day.
Messages before any dated user turn, and answers after an undated user turn,
have no assignable date unless they carry an explicit timestamp: they are
included when no bound is set and excluded when a start or end date is set.
The file modification time and the current clock are not used as dates.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

_CURSOR_TS_TAG_RE = re.compile(r"<timestamp>\s*(.*?)\s*</timestamp>", re.IGNORECASE | re.DOTALL)
_CURSOR_TS_BODY_RE = re.compile(
    r"^(.*?)\s*\(\s*UTC\s*([+-]\d{1,2})(?::?(\d{2}))?\s*\)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_CURSOR_USER_QUERY_RE = re.compile(r"<user_query>\s*(.*?)\s*</user_query>", re.IGNORECASE | re.DOTALL)

KINDS = ("chatgpt", "claude_code", "codex", "cursor", "livecaption", "gadget_summary")
KIND_LABELS = {
    "chatgpt": "ChatGPT 导出的聊天记录（conversations.json）",
    "claude_code": "Claude Code 聊天记录（不支持 Claude 应用导出）",
    "codex": "Codex 聊天记录",
    "cursor": "Cursor 聊天记录",
    "livecaption": "以前的 LiveCaption 语音文字（txt）",
    "gadget_summary": "以前生成的 gadget 摘要（JSON）",
}


def load_export(path: Path) -> dict:
    """Read one existing gadget device export, shared by CLI merge and automation."""
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or not isinstance(data.get('conversations'), list):
        raise ValueError('Invalid gadget export: conversations list required')
    for conversation in data['conversations']:
        if not isinstance(conversation, dict) or not isinstance(conversation.get('messages'), list):
            raise ValueError('Invalid gadget conversation')
        if any(not isinstance(m, dict) or not isinstance(m.get('content'), str) for m in conversation['messages']):
            raise ValueError('Invalid gadget message')
    return data


def _span(on_date, until_date):
    start = on_date.date() if isinstance(on_date, datetime) else on_date
    end = until_date.date() if isinstance(until_date, datetime) else until_date
    if start and end and end < start:
        raise ValueError("end date is before start date")
    if start and end is None:
        end = start
    return start, end


def _keeps(candidate, span) -> bool:
    """Inclusive local-date span. A missing timestamp is excluded once any bound is set."""
    start, end = span
    if start is None and end is None:
        return True
    if candidate is None:
        return False
    if start is not None and candidate < start:
        return False
    if end is not None and candidate > end:
        return False
    return True


def _local_day(stamp: str):
    when = _parse_iso(stamp)
    if when is None:
        return None
    return when.astimezone().date()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_records(
    kind: str,
    path: Path,
    *,
    on_date: datetime | None = None,
    until_date: datetime | None = None,
) -> tuple[list[dict], list[dict]]:
    """Return (text rows, summary rows). Raises ValueError on a bad file; writes nothing."""
    if kind not in KINDS:
        raise ValueError(f"unknown import kind {kind}")
    path = Path(path)
    if not path.exists():
        raise ValueError(f"path does not exist: {path}")
    day = _span(on_date, until_date)
    if kind == "gadget_summary":
        return [], _gadget_summaries(path)
    if kind == "chatgpt":
        if not path.is_file():
            raise ValueError("ChatGPT import expects the conversations.json export file")
        return _rows_from_conversations("chatgpt", _parse_chatgpt(path, day)), []
    files = _files_for(kind, path)
    conversations = []
    for file in files:
        previous = len(conversations)
        if kind == "claude_code":
            conversations.extend(_parse_claude_file(file, day))
        elif kind == "codex":
            conversations.extend(_parse_codex_file(file, day))
        elif kind == "cursor":
            conversations.extend(_parse_cursor_file(file, day))
        elif kind == "livecaption":
            conversations.extend(_parse_livecaption(file))
        project = file.parent.name
        if kind == "codex":
            project = _extract_codex_project(_jsonl(file))
        elif kind == "cursor" and len(file.parents) >= 3:
            project = file.parents[2].name if file.parent.parent.name == "agent-transcripts" else file.stem
        for conv in conversations[previous:]:
            conv["project"] = project
    source = "caption" if kind == "livecaption" else kind
    return _rows_from_conversations(source, conversations), []


def _files_for(kind: str, path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    if kind == "claude_code":
        found = [
            item
            for item in path.rglob("*.jsonl")
            if "subagents" not in item.parts and not item.name.startswith("agent-")
        ]
    elif kind == "codex":
        found = list(path.rglob("rollout-*.jsonl")) or list(path.rglob("*.jsonl"))
    elif kind == "cursor":
        found = [item for item in path.rglob("*.jsonl") if "subagents" not in item.parts]
    elif kind == "livecaption":
        found = list(path.rglob("*.txt"))
    else:
        found = []
    if not found:
        raise ValueError(f"no {kind} files under {path}")
    return sorted(found)


def _rows_from_conversations(source: str, conversations: list[dict]) -> list[dict]:
    rows = []
    for conv in conversations:
        conversation_id = str(conv["conversation_id"])
        for message in conv["messages"]:
            text = str(message["text"])
            seq = int(message["seq"]) if message.get("seq") else 0
            rows.append(
                {
                    "source": source,
                    "project": conv.get("project") or conversation_id,
                    "conversation_id": conversation_id,
                    "message_id": str(message["message_id"]),
                    "role": message["role"],
                    "ts": message.get("ts") or conv.get("ts") or "",
                    "seq": seq,
                    "text": text,
                    "content_hash": content_hash(text),
                }
            )
    return rows


def _parse_chatgpt(path: Path, day) -> list[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"ChatGPT export is not readable JSON: {exc}") from exc
    if not isinstance(data, list):
        raise ValueError("ChatGPT export must be a JSON array")
    conversations = []
    for conv in data:
        if not isinstance(conv, dict):
            continue
        mapping = conv.get("mapping") or {}
        if not mapping:
            continue
        nodes = {node_id: node for node_id, node in mapping.items() if isinstance(node, dict)}
        ordered = _chatgpt_current_branch(conv, nodes)
        messages = []
        branch_seq = 0
        for node_id in ordered:
            msg = (nodes[node_id].get("message") or {}) if node_id in nodes else {}
            if not msg:
                continue
            role = (msg.get("author") or {}).get("role", "")
            if role not in ("user", "assistant"):
                continue
            parts = (msg.get("content") or {}).get("parts") or []
            text = " ".join(str(part) for part in parts if isinstance(part, str)).strip()
            if not text:
                continue
            branch_seq += 1
            created = msg.get("create_time")
            if not _keeps(datetime.fromtimestamp(created).date() if created else None, day):
                continue
            stamp = datetime.fromtimestamp(created).isoformat() if created else ""
            messages.append(
                {"role": role, "text": text, "message_id": node_id, "ts": stamp, "seq": branch_seq}
            )
        if messages:
            identity = conv.get("conversation_id") or conv.get("id") or conv.get("title") or path.stem
            created = conv.get("create_time")
            conversations.append(
                {
                    "conversation_id": str(identity),
                    "ts": datetime.fromtimestamp(created).isoformat() if created else "",
                    "messages": messages,
                }
            )
    return conversations


def _chatgpt_current_branch(conv: dict, nodes: dict) -> list[str]:
    ordered: list[str] = []
    current = conv.get("current_node")
    if current and current in nodes:
        node_id = current
        while node_id and node_id in nodes:
            ordered.append(node_id)
            node_id = nodes[node_id].get("parent")
        ordered.reverse()
        return ordered
    root = next((node_id for node_id, node in nodes.items() if node.get("parent") is None), None)
    node_id = root
    while node_id and node_id in nodes:
        ordered.append(node_id)
        children = nodes[node_id].get("children") or []
        node_id = children[-1] if children else None
    return ordered


def _parse_claude_file(path: Path, day) -> list[dict]:
    messages = []
    for index, obj in enumerate(_jsonl(path), start=1):
        if obj.get("type") not in ("user", "assistant"):
            continue
        stamp = obj.get("timestamp") or ""
        when = _parse_iso(stamp)
        if not _keeps(None if when is None else when.astimezone().date(), day):
            continue
        message = obj.get("message") or {}
        role = message.get("role") or obj.get("type")
        if role not in ("user", "assistant"):
            continue
        text = _extract_blocks(message.get("content", ""))
        if not text:
            continue
        messages.append(
            {
                "role": role,
                "text": text,
                "message_id": str(obj.get("uuid") or f"line-{index}"),
                "ts": stamp,
                "seq": index,
            }
        )
    if not messages:
        return []
    return [{"conversation_id": path.stem, "ts": messages[0]["ts"], "messages": messages}]


def _parse_codex_file(path: Path, day) -> list[dict]:
    lines = _jsonl(path)
    if not lines:
        return []
    session_id = path.stem
    session_ts = ""
    collected: list[tuple[int, dict]] = []
    for index, entry in enumerate(lines):
        top = entry.get("type") or entry.get("record_type") or ""
        payload = entry.get("payload") or {}
        if top == "session_meta":
            session_id = str(payload.get("id") or session_id)
            session_ts = payload.get("timestamp") or entry.get("timestamp") or session_ts
            continue
        stamp = str(entry.get("timestamp") or payload.get("timestamp") or "")
        if top == "event_msg":
            kind = payload.get("type")
            role = "user" if kind == "user_message" else "assistant" if kind == "agent_message" else ""
            text = str(payload.get("message") or "").strip()
            if role and text and _keeps(_local_day(stamp), day):
                collected.append(
                    (
                        index,
                        {
                            "role": role,
                            "text": text,
                            "message_id": f"{session_id}:{index}",
                            "seq": index + 1,
                            "ts": stamp,
                        },
                    )
                )
            continue
        if top == "response_item":
            item = _codex_response_item(payload, session_id, index)
            if item is not None and _keeps(_local_day(stamp), day):
                item["ts"] = stamp
                collected.append((index, item))
            continue
        if top == "message":
            role = entry.get("role")
            text = _extract_blocks(entry.get("content", []))
            if role in ("user", "assistant") and text and _keeps(_local_day(stamp), day):
                collected.append(
                    (
                        index,
                        {
                            "role": role,
                            "text": text,
                            "message_id": f"{session_id}:{index}",
                            "seq": index + 1,
                            "ts": stamp,
                        },
                    )
                )
    messages = [item for _, item in collected]
    if not messages:
        return []
    return [{"conversation_id": session_id, "ts": session_ts, "messages": messages}]


def _codex_response_item(payload: dict, session_id: str, index: int) -> dict | None:
    kind = payload.get("type")
    if kind == "message":
        role = payload.get("role")
        text = _extract_blocks(payload.get("content", []))
        if role in ("user", "assistant") and text and not _codex_skipped(text):
            return {
                "role": role,
                "text": text,
                "message_id": f"{session_id}:{index}",
                "seq": index + 1,
            }
        return None
    if kind in ("function_call", "custom_tool_call"):
        name = payload.get("name", "unknown")
        tool_input = payload.get("arguments")
        if tool_input is None:
            tool_input = payload.get("input", "")
        return {
            "role": "assistant",
            "text": f"[Tool: {name}] {_truncate(tool_input, 300)}",
            "message_id": f"{session_id}:{index}",
            "seq": index + 1,
        }
    if kind in ("function_call_output", "custom_tool_call_output"):
        return {
            "role": "assistant",
            "text": f"[ToolResult] {_truncate(payload.get('output', ''), 500)}",
            "message_id": f"{session_id}:{index}",
            "seq": index + 1,
        }
    return None


def _parse_cursor_file(path: Path, day) -> list[dict]:
    """Keep untimestamped assistant answers with the current user turn.

    The turn date is the user message's own local date, or none when that user
    message has no timestamp. It is only a filter key. Messages selected by it
    keep an empty ts. Explicit timestamps still win and are stored.
    """
    messages = []
    turn_day = None
    for index, obj in enumerate(_jsonl(path), start=1):
        role = obj.get("role")
        if role not in ("user", "assistant"):
            continue
        message = obj.get("message") or {}
        content = message.get("content", "") if isinstance(message, dict) else ""
        raw = _cursor_text(content, strip_user_wrappers=False)
        stamp = _cursor_timestamp(raw)
        explicit_day = stamp.astimezone().date() if stamp is not None else None
        if role == "user":
            turn_day = explicit_day
        if explicit_day is not None:
            message_day = explicit_day
        elif role == "assistant":
            message_day = turn_day
        else:
            message_day = None
        text = _cursor_text(content, strip_user_wrappers=(role == "user"))
        if text and _keeps(message_day, day):
            messages.append(
                {
                    "role": role,
                    "text": text,
                    "message_id": f"line-{index}",
                    "ts": stamp.isoformat() if stamp is not None else "",
                    "seq": index,
                }
            )
    if not messages:
        return []
    # Leave conversation ts empty so an inferred answer does not inherit an ISO stamp.
    return [{"conversation_id": path.stem, "ts": "", "messages": messages}]


def _parse_livecaption(path: Path) -> list[dict]:
    messages = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        text = line.strip()
        if not text:
            continue
        messages.append(
            {"role": "caption", "text": text, "message_id": f"line-{index}", "ts": "", "seq": index}
        )
    if not messages:
        return []
    return [{"conversation_id": path.stem, "ts": "", "messages": messages}]


def _gadget_summaries(path: Path) -> list[dict]:
    if path.is_dir():
        files = sorted(path.rglob("*.json"))
    else:
        files = [path]
    rows = []
    for file in files:
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"gadget summary is not readable JSON: {file}: {exc}") from exc
        body = json.dumps(data, ensure_ascii=False, sort_keys=True)
        rows.append(
            {
                "source": "gadget",
                "conversation_id": file.stem,
                "first_seq": 0,
                "last_seq": 0,
                "model": "imported",
                "prompt_hash": "import",
                "content_hash": content_hash(body),
                "body": body,
            }
        )
    return rows


def _jsonl(path: Path) -> list[dict]:
    rows = []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"cannot read {path}: {exc}") from exc
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _extract_blocks(content) -> str:
    if isinstance(content, str):
        text = content.strip()
        if _codex_skipped(text):
            return ""
        return text
    if isinstance(content, dict):
        if content.get("type") in ("input_text", "output_text", "text"):
            return _extract_blocks(content.get("text", ""))
        nested = content.get("content")
        if nested is not None:
            return _extract_blocks(nested)
        return ""
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                text = _extract_blocks(block)
            elif isinstance(block, dict) and block.get("type") in ("text", "input_text", "output_text"):
                text = _extract_blocks(block.get("text", ""))
            elif isinstance(block, dict) and block.get("type") == "tool_use":
                raw = json.dumps(block.get("input", {}), ensure_ascii=False)
                text = f"[Tool: {block.get('name', 'unknown')}] {_truncate(raw, 300)}"
            elif isinstance(block, dict) and block.get("type") == "tool_result":
                text = f"[ToolResult] {_truncate(_extract_blocks(block.get('content', '')), 500)}"
            else:
                text = ""
            if text:
                parts.append(text)
        return "\n".join(parts).strip()
    return ""


def _codex_skipped(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith(
        (
            "<user_instructions>",
            "<environment_context>",
            "<app-context>",
            "<permissions instructions>",
            "# AGENTS.md instructions",
        )
    )


def _truncate(value, limit: int) -> str:
    if not isinstance(value, str):
        try:
            value = json.dumps(value, ensure_ascii=False)
        except TypeError:
            value = str(value)
    if len(value) > limit:
        return value[:limit] + "..."
    return value


def _cursor_text(content, *, strip_user_wrappers: bool) -> str:
    parts = []
    if isinstance(content, str):
        parts.append(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text" and block.get("text"):
                parts.append(block["text"])
    text = "\n".join(parts).strip()
    if not text or not strip_user_wrappers:
        return text
    text = _CURSOR_TS_TAG_RE.sub("", text).strip()
    match = _CURSOR_USER_QUERY_RE.search(text)
    if match:
        text = match.group(1).strip()
    return text.strip()


def _cursor_timestamp(text: str):
    if not text:
        return None
    match = _CURSOR_TS_TAG_RE.search(text)
    body = (match.group(1) if match else text).strip()
    if not body:
        return None
    offset = timezone.utc
    body_match = _CURSOR_TS_BODY_RE.match(body)
    if body_match:
        body = body_match.group(1).strip()
        hours = int(body_match.group(2))
        minutes = int(body_match.group(3) or 0)
        sign = 1 if hours >= 0 else -1
        offset = timezone(timedelta(hours=hours, minutes=sign * minutes))
    for fmt in ("%A, %b %d, %Y, %I:%M %p", "%A, %B %d, %Y, %I:%M %p", "%a, %b %d, %Y, %I:%M %p"):
        try:
            return datetime.strptime(body, fmt).replace(tzinfo=offset)
        except ValueError:
            continue
    return None


def _parse_iso(value: str):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_codex_project(lines: list[dict]) -> str:
    """从 Codex 会话中提取项目名（通过 environment_context 的 cwd）。"""
    for entry in lines:
        if entry.get("type") == "session_meta":
            cwd = (entry.get("payload") or {}).get("cwd")
            if cwd:
                return Path(cwd).name or cwd

    for entry in lines:
        payload = entry.get("payload") or {}
        if payload.get("type") == "message":
            for block in payload.get("content", []):
                if not isinstance(block, dict):
                    continue
                text = block.get("text", "")
                if "<cwd>" in text:
                    m = re.search(r"<cwd>(.*?)</cwd>", text)
                    if m:
                        return Path(m.group(1)).name

        if entry.get("role") != "user" or entry.get("type") != "message":
            continue
        for block in entry.get("content", []):
            text = block.get("text", "")
            if "<cwd>" in text:
                m = re.search(r"<cwd>(.*?)</cwd>", text)
                if m:
                    return Path(m.group(1)).name
    return "unknown"

