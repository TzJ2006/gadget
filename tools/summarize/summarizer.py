"""AI summarization module — prompt construction, conversation formatting, and LLM dispatch.

Extracted from daily_summary.py. Provides the core summarization pipeline:
prompt templates, conversation chunking, tool-use schema, and hierarchical
LLM call orchestration for daily reports.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import date
from pathlib import Path
from typing import Optional

from common.llm import (
    LLMCallConfig,
    timed_llm_call,
    load_chunk_cache as _load_chunk_cache,
    save_chunk_cache as _save_chunk_cache,
    cleanup_chunk_cache as _cleanup_chunk_cache,
    hierarchical_merge,
)
from common.json_utils import (
    parse_json_response as _parse_json_response,
    repair_json_with_llm as _repair_json_with_llm,
    try_repair_result,
)
from common.paths import CACHE_DIR

_DEFAULT_CACHE_DIR = CACHE_DIR / "summarize"

# ─── Prompt templates ─────────────────────────────────────────────

SUMMARY_PROMPT = """You are a professional daily report analyst. Based on the following AI conversation logs, generate a structured daily report.

The conversation logs come from AI interactions across the following projects (may include multiple sessions).

Analyze the conversation content, extract the following information, and return it in JSON format:

```json
{
    "date": "YYYY-MM-DD",
    "summary": "One-sentence summary of today's work",
    "daily_overview": {
        "what": "What was done (one sentence summarizing the core work of the day)",
        "how": "How it was done (one sentence summarizing the methods, tools, or key technical approaches)",
        "impact": "What it achieves (one sentence summarizing the significance of outcomes or project advancement)"
    },
    "tasks": [
        {
            "name": "Task name",
            "status": "completed | in_progress | blocked",
            "description": "Task description",
            "level": "high | low",
            "importance": 8
        }
    ],
    "problems_and_solutions": [
        {
            "problem": "Problem encountered",
            "solution": "Solution applied",
            "key_insight": "Key insight gained",
            "level": "high | low",
            "importance": 7
        }
    ],
    "human_vs_ai": [
        {
            "topic": "Topic",
            "human_approach": "Human's reasoning or key idea",
            "ai_approach": "AI's reasoning",
            "difference": "Analysis of the difference",
            "level": "high | low",
            "importance": 6
        }
    ],
    "ai_limitations": [
        {"content": "Limitation exhibited by AI during this interaction", "level": "high | low", "importance": 5}
    ],
    "learnings": [
        {"content": "Key takeaway from today", "level": "high | low", "importance": 9}
    ],
    "conversation_summaries": [
        {
            "project": "Human-readable project name (e.g. CalendarPro, not path format)",
            "source": "claude_code | codex | cursor | chatgpt | generic",
            "timestamp": "Original timestamp of this session",
            "topic": "Session topic title (60 characters or fewer)",
            "summary": "2-4 sentence narrative: what was discussed, key decisions, final outcome",
            "outcome": "completed | partial | exploratory | abandoned",
            "level": "high | low",
            "importance": 7
        }
    ]
}
```

Requirements:
1. Carefully distinguish the contributions of the human (user) and the AI (assistant)
2. Pay special attention to ideas proposed by the human that the AI did not think of
3. Record mistakes made by the AI or areas where human correction was needed
4. Task status must accurately reflect actual completion state
5. Return only JSON, do not add any other text
6. Use English
7. Generate one summary per independent session (conversation_summaries); use human-readable project names rather than path format; outcome should reflect actual completion state
8. Assign level and importance to each entry:
   - level: "high" = strategic thinking, architectural decisions, new methodologies, important discoveries; "low" = implementation details, bug fixes, routine work, environment setup
   - importance: integer from 1-10, where 10 is most important. Criteria: impact on project progress, technical depth, whether it changes direction
   - ai_limitations and learnings use the {"content": "...", "level": "...", "importance": N} object format
9. daily_overview should be distilled from the entire day's work; the three fields cover "what was done", "how it was done", and "what it achieves" respectively, one sentence each, without repetition

Conversation logs:
"""

_OVERVIEW_FLAT_BLOCK = '''"daily_overview": {
        "what": "What was done (one sentence summarizing the core work of the day)",
        "how": "How it was done (one sentence summarizing the methods, tools, or key technical approaches)",
        "impact": "What it achieves (one sentence summarizing the significance of outcomes or project advancement)"
    }'''

_OVERVIEW_FLAT_REQ = '9. daily_overview should be distilled from the entire day\'s work; the three fields cover "what was done", "how it was done", and "what it achieves" respectively, one sentence each, without repetition'


def _build_summary_prompt(device_labels: list[str] | None = None) -> str:
    """返回适用于单设备或多设备的 SUMMARY_PROMPT。"""
    if not device_labels or len(device_labels) <= 1:
        return SUMMARY_PROMPT

    # 构造多设备 daily_overview JSON 块
    devices_entries = ",\n            ".join(
        f'"{dev}": {{"what": "...", "how": "...", "impact": "..."}}'
        for dev in device_labels
    )
    multi_block = f'''"daily_overview": {{
        "global": {{"what": "Cross-device summary of core work for the day", "how": "Overall methods and technical approaches for the day", "impact": "Overall significance of the day's outcomes"}},
        "devices": {{
            {devices_entries}
        }}
    }}'''

    multi_req = (
        "9. daily_overview has two layers: global is a cross-device summary of the entire day (three sentences: what/how/impact), "
        "devices provides a per-device breakdown with three sentences each. "
        f"Device name list: {device_labels}"
    )

    prompt = SUMMARY_PROMPT.replace(_OVERVIEW_FLAT_BLOCK, multi_block)
    prompt = prompt.replace(_OVERVIEW_FLAT_REQ, multi_req)
    return prompt


MERGE_PROMPT_PREFIX = """You are a professional daily report analyst. The following conversations come from AI interaction logs across multiple devices. Please consolidate them into a complete structured daily report.

"""

MERGE_DEVICE_SUMMARY_PREFIX = """Some devices already have preliminary summaries. Please consolidate based on these:

"""

CHUNK_MERGE_PROMPT = """You are a professional daily report analyst. Below are independent summaries (in JSON format) of multiple conversation segments from the same day. Please merge them into a single complete structured daily report.

Requirements:
1. Merge all tasks; consolidate similar or identical tasks into one entry and keep the latest status
2. Merge all problems and solutions; consolidate similar problems into one entry
3. Merge all human vs AI analyses; consolidate entries on the same topic
4. Merge all AI limitations and learnings; consolidate similar content into one entry
5. Merge all conversation summaries (conversation_summaries); combine multiple sessions from the same project into one summary, keep one entry per distinct project
6. Generate a one-sentence summary covering all segments' work
7. Merge daily_overview from each segment: if segments use per-device grouped format (with global and devices), preserve the structure and merge content within the same device, with global covering the entire day; if in flat format ({what/how/impact}), synthesize a comprehensive three-sentence overview of the full day
8. Return the same JSON structure as the individual segments
9. Use English
10. Return only JSON, do not add any other text
11. Preserve the level and importance fields for each entry; when deduplicating, keep the higher importance value
12. ai_limitations and learnings use the {"content": "...", "level": "...", "importance": N} object format
13. Focus on synthesizing and distilling, not copying entries verbatim

"""


def _format_conversation(conv: dict) -> str:
    """将单个对话格式化为文本。"""
    device_info = ""
    if "device" in conv:
        d = conv["device"]
        device_label = d.get("device_name") or d.get("hostname", "unknown")
        device_info = f" | Device: {device_label}"
    header = f"\n{'='*60}\nSource: {conv['source']} | Project: {conv.get('project', 'N/A')} | Time: {conv['timestamp']}{device_info}\n{'='*60}\n"
    parts = [header]
    for msg in conv["messages"]:
        role_label = "👤 User" if msg["role"] == "user" else "🤖 Assistant"
        content = msg["content"]
        # 截断单条过长的消息
        if len(content) > 3000:
            content = content[:3000] + "\n... [truncated]"
        parts.append(f"\n{role_label}:\n{content}\n")
    return "".join(parts)


def _get_device_label(conv: dict) -> str:
    """从对话中提取设备标签。"""
    if "device" in conv:
        d = conv["device"]
        return d.get("device_name") or d.get("hostname", "unknown")
    return "unknown"


def format_conversations(conversations: list[dict]) -> str:
    """将对话列表格式化为文本（不截断，完整保留所有对话内容）。"""
    return "".join(_format_conversation(conv) for conv in conversations)


def chunk_conversations(conversations: list[dict], max_chars: int = 150000) -> list[list[dict]]:
    """按对话边界切分，使每个 chunk 格式化后 < max_chars。"""
    chunks, current, size = [], [], 0
    for conv in conversations:
        conv_len = len(_format_conversation(conv))
        if size + conv_len > max_chars and current:
            chunks.append(current)
            current, size = [], 0
        current.append(conv)
        size += conv_len
    if current:
        chunks.append(current)
    return chunks


def _chunk_content_hash(chunk: list[dict]) -> str:
    """对单个 chunk 的格式化文本计算 SHA-256，返回前 16 位 hex。"""
    text = format_conversations(chunk)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _conversations_hash(conversations: list[dict], context: str = "") -> str:
    """对 prompt 上下文 + 全部对话的格式化文本计算 SHA-256，返回前 16 位 hex。

    用于全局失效检测：*context*（prompt 前缀 + 设备摘要等 extra_context）也是
    LLM 真实输入的一部分，纳入哈希后，prompt/上下文变化能正确失效 chunk 缓存。
    """
    text = context + format_conversations(conversations)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]



# ── 日报 tool use schema（Anthropic 专用）──────────────────────────

def _daily_tool_schema() -> list[dict]:
    """返回 Anthropic tool use schema for submit_report（日报）。"""
    _lp = {
        "level": {"type": "string", "enum": ["high", "low"]},
        "importance": {"type": "integer", "minimum": 1, "maximum": 10},
    }
    return [{
        "name": "submit_report",
        "description": "Submit structured daily report",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string"},
                "summary": {"type": "string"},
                "daily_overview": {"type": "object"},
                "tasks": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "status": {"type": "string"},
                                   "description": {"type": "string"}, **_lp},
                    "required": ["name", "status", "description", "level", "importance"],
                }},
                "problems_and_solutions": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"problem": {"type": "string"}, "solution": {"type": "string"},
                                   "key_insight": {"type": "string"}, **_lp},
                    "required": ["problem", "solution", "level", "importance"],
                }},
                "human_vs_ai": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"topic": {"type": "string"}, "human_approach": {"type": "string"},
                                   "ai_approach": {"type": "string"}, "difference": {"type": "string"}, **_lp},
                    "required": ["topic", "level", "importance"],
                }},
                "ai_limitations": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"content": {"type": "string"}, **_lp},
                    "required": ["content", "level", "importance"],
                }},
                "learnings": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"content": {"type": "string"}, **_lp},
                    "required": ["content", "level", "importance"],
                }},
                "conversation_summaries": {"type": "array", "items": {
                    "type": "object",
                    "properties": {"project": {"type": "string"}, "source": {"type": "string"},
                                   "timestamp": {"type": "string"}, "topic": {"type": "string"},
                                   "summary": {"type": "string"},
                                   "outcome": {"type": "string", "enum": ["completed", "partial", "exploratory", "abandoned"]},
                                   **_lp},
                    "required": ["project", "topic", "summary", "level", "importance"],
                }},
            },
            "required": ["date", "summary", "tasks"],
        },
    }]


_LOW_THINKING = {"type": "enabled", "budget_tokens": 1024}


def _build_daily_config(conversations: list[dict], target_date: date,
                        prompt_prefix: str = SUMMARY_PROMPT,
                        extra_context: str = "",
                        timeout: int = 600) -> LLMCallConfig:
    """构建日报专用的 LLMCallConfig。"""
    conv_text = format_conversations(conversations)
    prompt = prompt_prefix + extra_context + conv_text + f"\n\nToday's date: {target_date.isoformat()}"
    return LLMCallConfig(
        prompt=prompt,
        timeout=timeout,
        anthropic_tools=_daily_tool_schema(),
        anthropic_tool_name="submit_report",
        thinking=_LOW_THINKING,
    )


# Known first-choice synonyms for the required `summary` field, tried in order.
_SUMMARY_SYNONYMS = ("one_sentence_summary", "one_line_summary", "summary_text",
                     "overall_summary", "daily_summary")

# Report fields that identify a dict as "the real report" (vs. a wrapper envelope).
_REPORT_SIGNAL_KEYS = ("summary", "tasks", "daily_overview", "conversation_summaries")
# Envelope keys qwen tends to nest the report under, tried before other dict children.
_ENVELOPE_KEYS = ("data", "result", "report", "output", "arguments", "response")


def _report_content_score(d) -> int:
    """How strongly *d* looks like the real report — signal keys + summary
    synonyms present. Higher = richer; 0 = not report-like (a wrapper or a thin
    decoy sub-object like ``{"statistics": {"summary": "3 tasks"}}``)."""
    if not isinstance(d, dict):
        return 0
    score = len(set(d) & set(_REPORT_SIGNAL_KEYS))
    score += sum(1 for k in _SUMMARY_SYNONYMS
                 if isinstance(d.get(k), str) and d[k].strip())
    return score


def _unwrap_envelope(result: dict) -> dict:
    """Unwrap a report nested inside a wrapper envelope.

    qwen sometimes returns `{"id": ..., "name": ..., "data": {<real report>}}`
    instead of the report itself. Only unwrap when the top level has NO report
    content of its own (so a top-level report with merely *renamed* keys is left
    for synonym recovery, not replaced by a nested decoy), and then pick the
    RICHEST nested dict — envelope keys win ties — so a thin decoy sub-object
    can't shadow the real report.
    """
    if not isinstance(result, dict) or _report_content_score(result) > 0:
        return result
    candidates = [result[k] for k in _ENVELOPE_KEYS if isinstance(result.get(k), dict)]
    candidates += [v for k, v in result.items()
                   if k not in _ENVELOPE_KEYS and isinstance(v, dict)]
    best, best_score = None, 0
    for inner in candidates:
        s = _report_content_score(inner)
        if s > best_score:
            best, best_score = inner, s
    return best if best is not None else result


def _renest_overview(result: dict) -> dict:
    """Re-nest a report that is really just ``daily_overview``'s contents.

    qwen3.8 sometimes answers one level too deep — `{"global": {...},
    "devices": {...}}` instead of `{"daily_overview": {"global": ...}, ...}`.
    Valid JSON, wrong level, and every downstream field reads empty. Nesting it
    back and lifting `global.what` into `summary` salvages the overview instead
    of publishing a blank report. Tasks/conversation summaries are genuinely
    absent from such a response — they cannot be recovered, only the overview.
    """
    if _report_content_score(result) or not any(
            k in result for k in ("global", "devices")):
        return result
    g = result.get("global")
    summary = g.get("what") if isinstance(g, dict) else g
    if not (isinstance(summary, str) and summary.strip()):
        summary = ""
        for dev in (result.get("devices") or {}).values():
            cand = dev.get("what") if isinstance(dev, dict) else dev
            if isinstance(cand, str) and cand.strip():
                summary = cand
                break
    print("[warn] 模型把 daily_overview 的内容当成整份报告返回，已重新嵌套；"
          "本次响应中缺少 tasks / conversation_summaries")
    return {"daily_overview": result, "summary": summary.strip()}


def _normalize_report(result: dict) -> dict:
    """Recover the canonical `summary` field when the model renamed it.

    Local models (qwen via ollama) unpredictably rename the required top-level
    `summary` key (`one_sentence_summary`, `daily_summary`, …), wrap the whole
    report in an envelope, or answer with a sub-object — each of which silently
    empties the report. First unwrap any envelope, re-nest a bare
    ``daily_overview`` payload, then recover `summary` from a known synonym,
    else from any other top-level ``*summary*`` string field (the legit list
    `conversation_summaries` is skipped by the str guard).
    # ponytail: heuristic string-key match; if it ever grabs the wrong field,
    #           go back to an explicit synonym allowlist.
    """
    result = _unwrap_envelope(result)
    if not isinstance(result, dict) or result.get("summary"):
        return result
    result = _renest_overview(result)
    if result.get("summary"):
        return result
    for alt in _SUMMARY_SYNONYMS:
        if isinstance(result.get(alt), str) and result[alt].strip():
            result["summary"] = result[alt]
            return result
    for k in sorted(result):
        if k != "summary" and "summary" in k.lower() \
                and isinstance(result[k], str) and result[k].strip():
            result["summary"] = result[k]
            return result
    return result


def _finalize_report(call, attempts: int = 2) -> dict:
    """Run the report call, retrying once if it came back structurally wrong.

    Even with schema-constrained decoding, qwen3.8 still answers one level too
    deep on roughly a third of real merges — `{"global": ..., "devices": ...}`,
    the contents of `daily_overview`, as the whole report. Sampling is the only
    difference between a good and a bad answer, so one retry is worth far more
    than any prompt wording: it costs a single merge call (~2 min) and only on
    the runs that already failed, while the chunk summaries stay computed.
    `_normalize_report` still salvages whatever the last attempt returned, so a
    retry that also fails is no worse than not retrying.
    """
    result = call()
    for _ in range(attempts - 1):
        if _report_content_score(result):
            break
        print("[warn] 合并结果结构不符（模型答深了一层），重试一次...")
        result = call()
    return _normalize_report(result)


def _call_summarize(api: str, conversations: list[dict], target_date: date,
                    prompt_prefix: str = SUMMARY_PROMPT,
                    extra_context: str = "",
                    timeout: int = 600,
                    chunk_cache_dir: Optional[Path] = None) -> dict:
    """层级递归总结：将对话分段独立总结，再逐层合并，避免截断丢失信息。"""
    chunks = chunk_conversations(conversations)
    n = len(chunks)

    if n == 1:
        config = _build_daily_config(chunks[0], target_date, prompt_prefix, extra_context, timeout)
        return _finalize_report(
            lambda: timed_llm_call(api, config, chunk_idx=1, total=1))

    total_chars = sum(len(format_conversations(c)) for c in chunks)
    print(f"[info] 对话总量 {total_chars:,} 字符，分为 {n} 段进行层级总结 "
          f"(每段时限 {timeout}s，总时限 ~{timeout * n}s)...")

    global_hash = (_conversations_hash(conversations, prompt_prefix + extra_context)
                   if chunk_cache_dir else None)

    chunk_summaries = []
    cache_hits = 0
    for i, chunk in enumerate(chunks):
        chunk_chars = len(format_conversations(chunk))

        if chunk_cache_dir and global_hash:
            c_hash = _chunk_content_hash(chunk)
            cached = _load_chunk_cache(chunk_cache_dir, c_hash, global_hash, n)
            if cached is not None:
                cache_hits += 1
                print(f"[info] 第 {i+1}/{n} 段命中缓存 ({chunk_chars:,} 字符, {len(chunk)} 个会话)")
                chunk_summaries.append(cached)
                continue

        print(f"[info] 正在总结第 {i+1}/{n} 段 ({chunk_chars:,} 字符, {len(chunk)} 个会话)...")
        config = _build_daily_config(chunk, target_date, prompt_prefix, extra_context, timeout)
        result = timed_llm_call(api, config, chunk_idx=i+1, total=n)
        chunk_summaries.append(result)

        if chunk_cache_dir and global_hash:
            _save_chunk_cache(chunk_cache_dir, c_hash, result, global_hash, n)

    if cache_hits:
        print(f"[info] chunk 缓存统计: {cache_hits}/{n} 命中, {n - cache_hits} 调用 API")

    def _daily_merge_config(prompt_text: str) -> LLMCallConfig:
        return LLMCallConfig(
            prompt=prompt_text,
            anthropic_tools=_daily_tool_schema(),
            anthropic_tool_name="submit_report",
            thinking=_LOW_THINKING,
        )

    return _finalize_report(
        lambda: hierarchical_merge(api, chunk_summaries, CHUNK_MERGE_PROMPT,
                                   _daily_merge_config, timeout))
