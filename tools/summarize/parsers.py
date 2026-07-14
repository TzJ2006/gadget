"""Conversation parsing utilities for multiple AI assistant log formats.

Parsers for Claude Code, Codex, ChatGPT export, and generic JSON conversation
formats. Each parser returns a list of unified conversation dicts.
"""

import json
import os
import platform
import re
import sys
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from .config import _load_config


def _is_dir(p: Path) -> bool:
    """is_dir() that treats unreadable paths as absent (locked /mnt/c sys accounts)."""
    try:
        return p.is_dir()
    except OSError:
        return False


def _home_dirs() -> list[Path]:
    """要扫描的 home 目录集合。

    始终包含真实 home；在 WSL 下，Claude/Codex 的数据写在 Windows 用户目录而非
    Linux home，因此额外把 /mnt/c/Users/* 也加进来。
    """
    homes = [Path.home()]
    # ponytail: 用内核字符串判断 WSL，既便宜又可靠（WSL1/2 都含 "microsoft"）。
    if "microsoft" in platform.uname().release.lower():
        win_users = Path("/mnt/c/Users")  # ponytail: 假设 C 盘挂在 /mnt/c（默认）
        if _is_dir(win_users):
            homes.extend(p for p in win_users.iterdir() if _is_dir(p))
    return homes


def _discover_claude_project_dirs() -> list[Path]:
    """发现所有 ~/.claude*/projects/ 目录（支持 .claude、.claude-code 等变体）。"""
    dirs = []
    for home in _home_dirs():
        for candidate in sorted(home.glob(".claude*")):
            projects = candidate / "projects"
            if _is_dir(projects):
                dirs.append(projects)
    return dirs


def _discover_codex_session_dirs() -> list[Path]:
    """发现所有 ~/.codex/sessions/ 目录（WSL 下含 Windows 侧）。"""
    return [d for home in _home_dirs()
            if _is_dir(d := home / ".codex" / "sessions")]


# ─── 统一对话格式 ───────────────────────────────────────────────

# 每个 conversation 结构:
# {
#     "source": "claude_code" | "codex" | "chatgpt" | "generic",
#     "project": "project_name",
#     "timestamp": "ISO8601",
#     "messages": [{"role": "user"|"assistant", "content": "..."}]
# }


def _extract_text_content(content) -> str:
    """从 Claude Code 的 content 字段提取纯文本。"""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    # 简要记录工具调用
                    name = block.get("name", "unknown")
                    inp = block.get("input", {})
                    # 截断过长的输入
                    inp_str = json.dumps(inp, ensure_ascii=False)
                    if len(inp_str) > 300:
                        inp_str = inp_str[:300] + "..."
                    parts.append(f"[Tool: {name}] {inp_str}")
                elif block.get("type") == "tool_result":
                    # 截断过长的工具结果
                    result_content = block.get("content", "")
                    result_str = _extract_text_content(result_content)
                    if len(result_str) > 500:
                        result_str = result_str[:500] + "..."
                    parts.append(f"[ToolResult] {result_str}")
        return "\n".join(parts).strip()
    return ""


def discover_all_dates() -> set[date]:
    """扫描 ~/.claude/projects/ 和 ~/.codex/sessions/ 下所有 JSONL，返回存在对话记录的所有日期集合。"""
    dates = set()

    # Claude Code 对话（自动发现 ~/.claude*/projects/）
    for claude_dir in _discover_claude_project_dirs():
        for project_dir in claude_dir.iterdir():
            if not project_dir.is_dir():
                continue
            if project_dir.name.endswith("-summarize"):
                continue
            for jsonl_file in project_dir.glob("*.jsonl"):
                if jsonl_file.name.startswith("agent-"):
                    continue
                try:
                    with open(jsonl_file, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                obj = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            if obj.get("type") not in ("user", "assistant"):
                                continue
                            ts_str = obj.get("timestamp")
                            if not ts_str:
                                continue
                            try:
                                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                                # 时间戳是 UTC；转本地后取日期，与 target_date（本地）
                                # 及 Codex 的本地目录日期保持同一日历口径。
                                dates.add(ts.astimezone().date())
                            except (ValueError, AttributeError):
                                continue
                except (OSError, UnicodeDecodeError):
                    continue

    # Codex 对话（按日期目录组织：~/.codex/sessions/YYYY/MM/DD/）
    for codex_dir in _discover_codex_session_dirs():
        for year_dir in codex_dir.iterdir():
            if not year_dir.is_dir():
                continue
            for month_dir in year_dir.iterdir():
                if not month_dir.is_dir():
                    continue
                for day_dir in month_dir.iterdir():
                    if not day_dir.is_dir():
                        continue
                    # 目录名即日期组件
                    try:
                        d = date(int(year_dir.name), int(month_dir.name),
                                 int(day_dir.name))
                        # 确认目录下有 JSONL 文件
                        if any(day_dir.glob("rollout-*.jsonl")):
                            dates.add(d)
                    except (ValueError, TypeError):
                        continue

    return dates


def parse_claude_code(target_date: date) -> list[dict]:
    """扫描所有 ~/.claude*/projects/ 下的项目，按日期筛选 user/assistant 消息。"""
    claude_dirs = _discover_claude_project_dirs()
    if not claude_dirs:
        print("[warn] 未找到任何 Claude Code 项目目录 (~/.claude*/projects/)")
        return []

    conversations = []

    for claude_dir in claude_dirs:
        for project_dir in claude_dir.iterdir():
            if not project_dir.is_dir():
                continue
            project_name = project_dir.name

            if project_name.endswith("-summarize"):
                continue

            for jsonl_file in project_dir.glob("*.jsonl"):
                if jsonl_file.name.startswith("agent-"):
                    continue

                messages = []
                session_timestamp = None
                has_target_date = False

                try:
                    with open(jsonl_file, "r", encoding="utf-8") as f:
                        for line in f:
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                obj = json.loads(line)
                            except json.JSONDecodeError:
                                continue

                            msg_type = obj.get("type")
                            if msg_type not in ("user", "assistant"):
                                continue

                            timestamp_str = obj.get("timestamp")
                            if not timestamp_str:
                                continue

                            try:
                                ts = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
                            except (ValueError, AttributeError):
                                continue

                            # UTC → 本地日期，与 target_date / Codex 口径一致
                            msg_date = ts.astimezone().date()
                            if msg_date != target_date:
                                continue

                            has_target_date = True
                            if session_timestamp is None:
                                session_timestamp = timestamp_str

                            message = obj.get("message", {})
                            role = message.get("role", msg_type)
                            content = message.get("content", "")

                            text = _extract_text_content(content)
                            if text:
                                messages.append({"role": role, "content": text})
                except (OSError, UnicodeDecodeError) as e:
                    print(f"[warn] 读取 {jsonl_file} 失败: {e}")
                    continue

                if has_target_date and messages:
                    conversations.append({
                        "source": "claude_code",
                        "project": project_name,
                        "timestamp": session_timestamp or target_date.isoformat(),
                        "messages": messages,
                    })

    return conversations


def parse_chatgpt_export(filepath: str, target_date: date) -> list[dict]:
    """解析 ChatGPT 导出的 conversations.json，按 create_time 筛选日期。"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[error] 读取 ChatGPT 导出失败: {e}")
        return []

    conversations = []

    for conv in data:
        title = conv.get("title", "untitled")
        create_time = conv.get("create_time")
        mapping = conv.get("mapping", {})

        if not mapping:
            continue

        # 从 mapping 中按顺序提取消息
        messages = []

        # 构建节点的 children 关系，找到根节点
        nodes_by_id = {}
        root_id = None
        for node_id, node in mapping.items():
            nodes_by_id[node_id] = node
            if node.get("parent") is None:
                root_id = node_id

        # 沿 current_node 回溯得到当前激活分支（编辑/重新生成后正确的那条），
        # 缺失时退回按最后一个 child（最新分支）前向遍历。原先取 children[0]
        # 会走到被废弃的旧分支。
        ordered_ids: list[str] = []
        current_node = conv.get("current_node")
        if current_node and current_node in nodes_by_id:
            cid = current_node
            while cid and cid in nodes_by_id:
                ordered_ids.append(cid)
                cid = nodes_by_id[cid].get("parent")
            ordered_ids.reverse()
        else:
            cid = root_id
            while cid and cid in nodes_by_id:
                ordered_ids.append(cid)
                children = nodes_by_id[cid].get("children", [])
                cid = children[-1] if children else None

        for current_id in ordered_ids:
            msg = nodes_by_id[current_id].get("message")
            if not msg:
                continue
            role = msg.get("author", {}).get("role", "")
            if role not in ("user", "assistant"):
                continue
            # 仅保留 create_time 落在目标日期（本地）的消息，避免跨天对话把
            # 其它日期的内容混进当天报告。与 Claude 解析口径一致。
            ct = msg.get("create_time")
            if not ct or datetime.fromtimestamp(ct).date() != target_date:
                continue
            parts = msg.get("content", {}).get("parts", [])
            text = " ".join(str(p) for p in parts if isinstance(p, str))
            if text.strip():
                messages.append({"role": role, "content": text.strip()})

        if messages:
            conversations.append({
                "source": "chatgpt",
                "project": title,
                "timestamp": datetime.fromtimestamp(create_time).isoformat() if create_time else target_date.isoformat(),
                "messages": messages,
            })

    return conversations


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


def _extract_codex_text(content) -> str:
    """从 Codex 的 content 字段提取纯文本。"""
    def _clean_text(text: str) -> str:
        text = text.strip()
        if not text:
            return ""
        skip_prefixes = (
            "<user_instructions>",
            "<environment_context>",
            "<app-context>",
            "<permissions instructions>",
            "# AGENTS.md instructions",
        )
        if any(text.startswith(prefix) for prefix in skip_prefixes):
            return ""
        return text

    if isinstance(content, str):
        return _clean_text(content)
    if isinstance(content, dict):
        block_type = content.get("type", "")
        if block_type in ("input_text", "output_text", "text"):
            return _clean_text(content.get("text", ""))
        nested = content.get("content")
        if nested is not None:
            return _extract_codex_text(nested)
        return ""
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                text = _clean_text(block)
                if text:
                    parts.append(text)
            elif isinstance(block, dict):
                text = _extract_codex_text(block)
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()
    return ""


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


def parse_codex(target_date: date) -> list[dict]:
    """扫描 ~/.codex/sessions/ 下按日期目录组织的 Codex 会话。

    Codex 会话存储在 ~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl，
    每个文件为一个独立会话。
    """
    # 定位目标日期的目录（WSL 下可能同时存在 Linux 与 Windows 侧）
    rel = f"{target_date.year}/{target_date.month:02d}/{target_date.day:02d}"
    day_dirs = [d / rel for d in _discover_codex_session_dirs()
                if _is_dir(d / rel)]
    if not day_dirs:
        return []

    conversations = []

    def _truncate_tool_value(value, limit: int) -> str:
        if isinstance(value, str):
            text = value
        else:
            try:
                text = json.dumps(value, ensure_ascii=False)
            except TypeError:
                text = str(value)
        if len(text) > limit:
            return text[:limit] + "..."
        return text

    for jsonl_file in sorted(f for d in day_dirs for f in d.glob("rollout-*.jsonl")):
        try:
            with open(jsonl_file, "r", encoding="utf-8") as f:
                lines = [json.loads(line.strip()) for line in f if line.strip()]
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            print(f"[warn] 读取 Codex 会话 {jsonl_file.name} 失败: {e}")
            continue

        if not lines:
            continue

        session_id = jsonl_file.stem
        session_ts = target_date.isoformat()
        project_name = _extract_codex_project(lines)
        event_messages: list[tuple[int, dict]] = []
        fallback_messages: list[tuple[int, dict]] = []
        tool_messages: list[tuple[int, dict]] = []

        for idx, entry in enumerate(lines):
            top_type = entry.get("type", entry.get("record_type", ""))
            payload = entry.get("payload") or {}

            if top_type == "session_meta":
                session_id = payload.get("id", session_id)
                session_ts = payload.get("timestamp") or entry.get("timestamp") or session_ts
                continue

            if top_type == "event_msg":
                payload_type = payload.get("type", "")
                if payload_type == "user_message":
                    text = payload.get("message", "").strip()
                    if text:
                        event_messages.append((idx, {"role": "user", "content": text}))
                elif payload_type == "agent_message":
                    text = payload.get("message", "").strip()
                    if text:
                        event_messages.append((idx, {"role": "assistant", "content": text}))
                continue

            if top_type == "response_item":
                payload_type = payload.get("type", "")
                if payload_type == "message":
                    role = payload.get("role", "")
                    if role in ("user", "assistant"):
                        text = _extract_codex_text(payload.get("content", []))
                        if text:
                            fallback_messages.append((idx, {"role": role, "content": text}))
                elif payload_type in ("function_call", "custom_tool_call"):
                    name = payload.get("name", "unknown")
                    tool_input = payload.get("arguments")
                    if tool_input is None:
                        tool_input = payload.get("input", "")
                    tool_messages.append((
                        idx,
                        {
                            "role": "assistant",
                            "content": f"[Tool: {name}] {_truncate_tool_value(tool_input, 300)}",
                        },
                    ))
                elif payload_type in ("function_call_output", "custom_tool_call_output"):
                    output = payload.get("output", "")
                    tool_messages.append((
                        idx,
                        {
                            "role": "assistant",
                            "content": f"[ToolResult] {_truncate_tool_value(output, 500)}",
                        },
                    ))
                continue

            # 兼容更旧的平铺格式
            if top_type == "message":
                role = entry.get("role", "")
                if role in ("user", "assistant"):
                    text = _extract_codex_text(entry.get("content", []))
                    if text:
                        fallback_messages.append((idx, {"role": role, "content": text}))
            elif top_type in ("function_call", "custom_tool_call"):
                name = entry.get("name", "unknown")
                tool_input = entry.get("arguments")
                if tool_input is None:
                    tool_input = entry.get("input", "")
                tool_messages.append((
                    idx,
                    {
                        "role": "assistant",
                        "content": f"[Tool: {name}] {_truncate_tool_value(tool_input, 300)}",
                    },
                ))
            elif top_type in ("function_call_output", "custom_tool_call_output"):
                tool_messages.append((
                    idx,
                    {
                        "role": "assistant",
                        "content": f"[ToolResult] {_truncate_tool_value(entry.get('output', ''), 500)}",
                    },
                ))

        plain_messages = event_messages if event_messages else fallback_messages
        combined = [msg for _, msg in sorted(plain_messages + tool_messages, key=lambda item: item[0])]

        if combined:
            conversations.append({
                "source": "codex",
                "project": project_name,
                "timestamp": session_ts,
                "messages": combined,
            })

    return conversations


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

    # 3. ChatGPT 导出
    if chatgpt:
        print(f"[info] 解析 ChatGPT 导出: {chatgpt}")
        chatgpt_convs = parse_chatgpt_export(chatgpt, target_date)
        print(f"[info] 找到 {len(chatgpt_convs)} 个 ChatGPT 会话")
        all_conversations.extend(chatgpt_convs)

    # 4. 通用格式
    for gpath in (generic or []):
        print(f"[info] 解析通用格式: {gpath}")
        generic_convs = parse_generic(gpath, target_date)
        print(f"[info] 找到 {len(generic_convs)} 个通用格式会话")
        all_conversations.extend(generic_convs)

    return all_conversations
