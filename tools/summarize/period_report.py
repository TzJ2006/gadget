"""Shared helpers for weekly and monthly period reports.

Period-specific prompts, tool schemas, and markdown live in weekly_summary /
monthly_summary. This module holds the copy-pasted pipeline: cache, chunked LLM
calls, Hugo frontmatter, argparse flags, and chart reshape.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional

from common.bilingual import write_bilingual
from common.io import atomic_write as _atomic_write
from common.llm import (
    DEFAULT_BACKEND,
    LLM_BACKENDS,
    LLMCallConfig,
    ChunkTimeoutError,
    chunk_text,
    timed_llm_call,
    load_chunk_cache as _load_chunk_cache,
    save_chunk_cache as _save_chunk_cache,
    cleanup_chunk_cache as _cleanup_chunk_cache,
    hierarchical_merge,
)
from common.paths import REPORTS_DIR, CACHE_DIR
from common.site_staging import resolve_site_content_dir, copy_site_static

from .config import _load_config, _resolve_output_dir, resolve_hugo_site


# ─── Named constants (A19=a); config keys override when present ────────

CHUNK_CHARS = 150_000
PROMPT_OVERHEAD = 200
TIMEOUT_DAILY = 600
TIMEOUT_WEEKLY = 1800  # long workstream/thread reports
TIMEOUT_MONTHLY = 3600

_LOW_THINKING = {"type": "enabled", "budget_tokens": 1024}

# Output budgets: daily 24K tokens; weekly may run ~5x a daily report, monthly ~4x
# a weekly. ponytail: capped by the shared 96K Ollama context — a 150K-char input
# chunk (~43K tokens) plus output must fit — so monthly stops at 48K output tokens,
# not a literal 4x weekly. Raise both with GADGET_OLLAMA_NUM_CTX if VRAM allows.
WEEKLY_MAX_TOKENS = 40960
MONTHLY_MAX_TOKENS = 49152

# ─── Shared report pieces (daily / weekly / monthly) ───────────────────

_STR = {"type": "string"}
_STRS = {"type": "array", "items": {"type": "string"}}

OBSTACLES_SCHEMA = {"type": "array", "items": {
    "type": "object",
    "properties": {"obstacle": _STR, "resolution": _STR},
    "required": ["obstacle"],
}}

WORKSTREAMS_SCHEMA = {"type": "array", "items": {
    "type": "object",
    "properties": {"topic": _STR, "dates": _STRS,
                   "sessions": {"type": "integer", "minimum": 1},
                   "outcome": _STR, "summary": _STR},
    "required": ["topic", "summary"],
}}

THREAD_SCHEMA = {"type": "array", "items": {
    "type": "object",
    "properties": {"project": _STR, "problem": _STR, "context": _STR,
                   "obstacles": OBSTACLES_SCHEMA, "solution": _STR, "key_insight": _STR,
                   "dates": _STRS, "level": {"type": "string", "enum": ["high", "low"]},
                   "importance": {"type": "integer", "minimum": 1, "maximum": 10}},
    "required": ["project", "problem", "solution"],
}}

# Extra problem sections every report level carries (merged into each tool schema).
PROBLEM_SECTION_SCHEMAS = {
    "cross_project_problems": {"type": "array", "items": {
        "type": "object",
        "properties": {"pattern": _STR, "projects": _STRS, "occurrences": {"type": "integer"},
                       "dates": _STRS, "how_resolved": _STR, "lesson": _STR},
        "required": ["pattern", "projects", "how_resolved"],
    }},
    "unresolved_problems": {"type": "array", "items": {
        "type": "object",
        "properties": {"project": _STR, "problem": _STR, "progress": _STR,
                       "why_stopped": _STR, "how_to_resume": _STR},
        "required": ["project", "problem", "progress"],
    }},
}

_PROBLEM_JSON = """    "THREAD_KEY": [
        {
            "project": "Related project",
            "problem": "What problem was being solved (the goal or the failure)",
            "context": "Starting conditions: environment, constraints, resources, what was already known or tried",
            "obstacles": [
                {"obstacle": "A difficulty hit along the way", "resolution": "How that difficulty was overcome"}
            ],
            "solution": "The final solution and its result",
            "key_insight": "Key insight gained",
            "dates": ["YYYY-MM-DD"],
            "level": "high | low",
            "importance": 7
        }
    ],
    "cross_project_problems": [
        {
            "pattern": "A problem that kept coming back, across projects or repeatedly",
            "projects": ["Project A", "Project B"],
            "occurrences": 3,
            "dates": ["YYYY-MM-DD"],
            "how_resolved": "How it was ultimately resolved, generalized across the occurrences",
            "lesson": "The reusable rule to apply next time"
        }
    ],
    "unresolved_problems": [
        {
            "project": "Related project",
            "problem": "What the problem is",
            "progress": "How far it got: what was tried, what works, where it stands now",
            "why_stopped": "Why work did not continue (blocked, deprioritized, out of time, ...)",
            "how_to_resume": "Fastest way to pick it up again: files, commands, first next step"
        }
    ],"""

_PROBLEM_RULES = (
    "THREAD_KEY is the most important section. Write one thread per problem actually worked on, with its "
    "project: what problem was solved, the starting conditions (environment, constraints, resources, what was "
    "already known or tried), every obstacle hit along the way and how each was overcome (in the order they "
    "occurred), then the final solution and result. Merge entries about the same problem into one thread; never "
    "drop a problem; include only obstacles that actually occurred. Put only resolved problems here.\n"
    "cross_project_problems: problems that recurred or went back and forth, especially ones that showed up in "
    "more than one project. For each, list the projects, how often it occurred, how it was ultimately resolved "
    "(generalized across the occurrences), and the reusable lesson. Use an empty array if nothing recurred.\n"
    "unresolved_problems: every problem worked on but not solved. For each: what it is, how far it got, why work "
    "did not continue, and how to pick it up quickly (files, commands, first next step). Only state reasons and "
    "next steps the logs support; use an empty array if everything was resolved."
)


def problem_json(thread_key: str) -> str:
    """JSON example for the three problem sections, spliced into each prompt."""
    return _PROBLEM_JSON.replace("THREAD_KEY", thread_key)


def problem_rules(thread_key: str) -> str:
    """Prompt rules for the three problem sections (shared by all report levels)."""
    return _PROBLEM_RULES.replace("THREAD_KEY", thread_key)


def _by_project(items: list) -> dict:
    groups: dict = {}
    for it in items or []:
        if isinstance(it, dict):
            groups.setdefault(it.get("project") or "Other", []).append(it)
    for g in groups.values():
        g.sort(key=lambda x: -int(x.get("importance") or 0))
    return groups


def render_problem_sections(lines: list[str], threads: list, cross: list,
                            unresolved: list) -> None:
    """Problem-solving threads by project, recurring problems, unresolved problems."""
    groups = _by_project(threads)
    if groups:
        lines.append("## Problem-Solving Threads\n")
        i = 1
        for project, items in groups.items():
            lines.append(f"### {project}\n")
            for t in items:
                when = ", ".join(t.get("dates") or []) or t.get("date") or ""
                lines.append(f"#### {i}. {t.get('problem', 'N/A')}" + (f" ({when})" if when else "") + "\n")
                if t.get("context"):
                    lines.append(f"**Conditions:** {t['context']}\n")
                obstacles = [o for o in (t.get("obstacles") or []) if isinstance(o, dict)]
                if obstacles:
                    lines.append("**Obstacles:**")
                    for o in obstacles:
                        res = f" → {o['resolution']}" if o.get("resolution") else ""
                        lines.append(f"- {o.get('obstacle', '')}{res}")
                    lines.append("")
                lines.append(f"**Solution:** {t.get('solution', 'N/A')}\n")
                if t.get("key_insight"):
                    lines.append(f"**Key Insight:** {t['key_insight']}\n")
                i += 1
    cross = [c for c in (cross or []) if isinstance(c, dict)]
    if cross:
        lines.append("## Recurring Problems Across Projects\n")
        for i, c in enumerate(cross, 1):
            n = f", {c['occurrences']}×" if c.get("occurrences") else ""
            lines.append(f"### {i}. {c.get('pattern', 'N/A')} ({', '.join(c.get('projects') or [])}{n})\n")
            lines.append(f"**How it was resolved:** {c.get('how_resolved', '—')}\n")
            if c.get("lesson"):
                lines.append(f"**Lesson:** {c['lesson']}\n")
    groups = _by_project(unresolved)
    if groups:
        lines.append("## Unresolved Problems\n")
        i = 1
        for project, items in groups.items():
            lines.append(f"### {project}\n")
            for u in items:
                lines.append(f"#### {i}. {u.get('problem', 'N/A')}\n")
                lines.append(f"**Progress:** {u.get('progress', '—')}\n")
                if u.get("why_stopped"):
                    lines.append(f"**Why it stopped:** {u['why_stopped']}\n")
                if u.get("how_to_resume"):
                    lines.append(f"**How to resume:** {u['how_to_resume']}\n")
                i += 1


def render_workstreams(lines: list[str], workstreams: list) -> None:
    """One line per workstream: topic, when, how many sessions, what happened."""
    for w in workstreams or []:
        if not isinstance(w, dict):
            lines.append(f"- {w}")
            continue
        meta = []
        if w.get("dates"):
            meta.append(", ".join(w["dates"]))
        if int(w.get("sessions") or 1) > 1:
            meta.append(f"{w['sessions']} sessions")
        meta_str = f" ({'; '.join(meta)})" if meta else ""
        lines.append(f"- **{w.get('topic', '')}**{meta_str}: {w.get('summary', '')}")
    lines.append("")


DEFAULT_REPORTS_DIR = REPORTS_DIR / "summarize"


def _cfg_int(*keys: str, default: int) -> int:
    """First positive int among config keys, else *default*."""
    cfg = _load_config()
    for key in keys:
        val = cfg.get(key)
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            continue
        parsed = int(val)
        if parsed > 0:
            return parsed
    return default


def resolved_chunk_chars() -> int:
    return _cfg_int("chunk_chars", "llm_chunk_chars", default=CHUNK_CHARS)


def resolved_timeout_daily() -> int:
    return _cfg_int("timeout_daily", default=TIMEOUT_DAILY)


def resolved_timeout_weekly() -> int:
    return _cfg_int("timeout_weekly", default=TIMEOUT_WEEKLY)


def resolved_timeout_monthly() -> int:
    return _cfg_int("timeout_monthly", default=TIMEOUT_MONTHLY)


# ─── Timezone (A7=c): local offset, not hardcoded -05:00 ───────────────

def local_tz_offset_str(when: Optional[datetime] = None) -> str:
    """Local UTC offset as ``±HH:MM`` (DST-aware for *when*)."""
    dt = (when or datetime.now()).astimezone()
    offset = dt.strftime("%z")  # +HHMM
    if not offset:
        return "+00:00"
    return offset[:3] + ":" + offset[3:]


def hugo_datetime(d: date, hour: int = 0, minute: int = 0, second: int = 0) -> str:
    """Hugo frontmatter datetime in the machine's local timezone."""
    local = datetime(d.year, d.month, d.day, hour, minute, second).astimezone()
    return local.strftime("%Y-%m-%dT%H:%M:%S") + local_tz_offset_str(local)


def _yaml_escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace('"', '\\"')
            .replace("\r", " ").replace("\n", " "))


def summary_from_markdown(markdown_body: str, fallback: str) -> str:
    summary = fallback
    for line in markdown_body.splitlines():
        if line.startswith("> "):
            summary = line[2:].strip()
            break
    return _yaml_escape(summary)


def generate_period_hugo_post(
    markdown_body: str,
    hugo_site: Path,
    *,
    title: str,
    post_date: date,
    keywords: list[str],
    fallback_summary: str,
    content_parts: tuple[str, ...],
    filename: str,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
    chart_path: Optional[Path] = None,
    chart_image_subdir: Optional[str] = None,
    api: str = DEFAULT_BACKEND,
    force: bool = False,
    overwrite_human: bool = False,
    engine=None,
    pbar=None,
) -> Path:
    """Write a bilingual Hugo bugJournal (or similar) post via write_bilingual.

    ``api`` is unused (translation is local-inference); kept so call sites that
    still pass it do not break.
    """
    _ = api
    summary = summary_from_markdown(markdown_body, fallback_summary)
    kw_yaml = "\n".join(f"- {k}" for k in keywords)
    stamp = hugo_datetime(post_date, hour=hour, minute=minute, second=second)
    frontmatter = f"""---
title: "{_yaml_escape(title)}"
date: {stamp}
keywords:
{kw_yaml}
summary: "{summary}"
draft: false
---

"""
    resolve_site_content_dir(hugo_site, *content_parts)

    if chart_path and chart_path.exists():
        subdir = chart_image_subdir or content_parts[-1]
        dest = copy_site_static(
            hugo_site, chart_path,
            Path("images") / subdir / chart_path.name, force=force)
        print(f"[ok] Chart copied to Hugo: {dest}")

    rel = Path(*content_parts) / filename
    en_path, zh_path = write_bilingual(
        hugo_site, rel, frontmatter + markdown_body,
        engine=engine, pbar=pbar, force=force,
        overwrite_human=overwrite_human, report=True)

    print(f"[ok] Hugo post generated: {en_path}")
    if zh_path:
        zh_text = zh_path.read_text(encoding="utf-8")
        localized = localize_report_labels_zh(zh_text, en=markdown_body)
        if localized != zh_text:
            _atomic_write(zh_path, localized)
        print(f"[ok] Hugo post (translated): {zh_path}")
    return en_path


# ─── zh label localization ─────────────────────────────────────────────
# The translation prompt keeps English headings as-is (right for blog titles,
# wrong for the fixed labels our renderers emit), so the zh post gets its
# report labels swapped deterministically after translation.
# ponytail: exact-label table; add a row when a renderer grows a new label.

_ZH_LABELS = {
    "Weekly Overview": "本周概览", "Monthly Overview": "本月概览", "Daily Overview": "今日概览",
    "Project Progress": "项目进展", "Problem-Solving Threads": "解决问题的脉络",
    "Recurring Problems Across Projects": "跨项目反复出现的问题",
    "Recurring Problems": "反复出现的问题", "Unresolved Problems": "未解决的问题",
    "Problems & Solutions": "问题与解决", "Key Tasks": "关键任务", "Tasks": "任务",
    "Key Achievements": "关键成果", "Learnings": "收获", "Monthly Learnings Digest": "本月收获精选",
    "AI Usage Notes": "AI 使用心得", "Human vs AI Approaches": "人与 AI 的思路差异",
    "Human-AI Collaboration Trends": "人机协作趋势", "AI Limitations": "AI 的局限",
    "Next Week Outlook": "下周展望", "Token Usage Statistics": "Token 用量统计",
    "Token Usage": "Token 用量", "Conversation Summaries": "会话摘要",
    "Critical Issues": "关键问题", "General Issues": "一般问题",
    "Strategic Level": "战略层面", "Implementation Level": "实现层面",
    "Architecture & Strategy": "架构与策略", "Implementation & Fixes": "实现与修复",
    "Architecture (architecture)": "架构", "Debugging (debugging)": "调试",
    "Tools (tools)": "工具", "Domain Knowledge (domain)": "领域知识",
}
_ZH_BOLD = {
    "Conditions": "条件", "Obstacles": "遇到的难题", "Solution": "解决方案",
    "Key Insight": "关键收获", "How it was resolved": "最终如何解决", "Lesson": "经验",
    "Progress": "进展", "Why it stopped": "为什么没有继续", "How to resume": "如何快速上手",
    "Accomplishments": "成果", "Blockers": "阻塞", "Key Milestones": "关键里程碑",
    "Effective Patterns": "有效做法", "Limitations": "局限", "Dates": "日期",
    "Root Cause": "根因", "Status": "状态", "Peak Day": "峰值日", "Daily Average": "日均",
}
_ZH_INLINE = [
    (re.compile(r"\((\d+|\?) days active\)"), r"（活跃 \1 天）"),
    (re.compile(r"\b(\d+) sessions\b"), r"\1 个会话"),
    (re.compile(r"🔄 active\b"), "🔄 进行中"), (re.compile(r"✅ completed\b"), "✅ 已完成"),
    (re.compile(r"⏸️ paused\b"), "⏸️ 暂停"),
]
_ZH_HEADING_RE = re.compile(r"^(#{2,4} )(.+?)[ \t]*$", re.M)
_ZH_BOLD_RE = re.compile(r"\*\*(" + "|".join(map(re.escape, _ZH_BOLD)) + r"):\*\*")


_LINE_HEADING_RE = re.compile(r"^(#{2,4} )(.*?)[ \t]*$", re.M)
_LINE_BOLD_RE = re.compile(r"^\*\*([^*\n]{1,30}?)[:：]\*\*", re.M)


def _align(zh: str, en: str, pattern: re.Pattern, fix) -> str:
    """Rewrite the i-th zh match from the i-th en match when both sides have the
    same number of matches (the model keeps structure; it only varies wording)."""
    en_m, zh_m = list(pattern.finditer(en)), list(pattern.finditer(zh))
    if len(en_m) != len(zh_m):
        return zh
    out, last = [], 0
    for e, z in zip(en_m, zh_m):
        rep = fix(e, z)
        if rep is not None:
            out.append(zh[last:z.start()] + rep)
            last = z.end()
    return "".join(out) + zh[last:]


def localize_report_labels_zh(text: str, en: str | None = None) -> str:
    """Swap the renderers' fixed labels for fixed Chinese in a zh report body.

    With *en* (the source), labels are pinned by position, so the model's own
    wording (e.g. 问题解决线程) is replaced too; English leftovers are mapped either way.
    """
    if en:
        text = _align(text, en, _LINE_HEADING_RE, lambda e, z: (
            z.group(1) + _ZH_LABELS[e.group(2)] if e.group(2) in _ZH_LABELS else None))
        text = _align(text, en, _LINE_BOLD_RE, lambda e, z: (
            f"**{_ZH_BOLD[e.group(1)]}：**" if e.group(1) in _ZH_BOLD else None))
    text = _ZH_HEADING_RE.sub(
        lambda m: m.group(1) + _ZH_LABELS.get(m.group(2), m.group(2)), text)
    text = _ZH_BOLD_RE.sub(lambda m: f"**{_ZH_BOLD[m.group(1)]}：**", text)
    for pat, rep in _ZH_INLINE:
        text = pat.sub(rep, text)
    return text


# ─── Cache ─────────────────────────────────────────────────────────────

def period_cache_dir(kind: str) -> Path:
    return CACHE_DIR / "summarize" / kind


def compute_source_hash(daily_reports: list[dict]) -> str:
    """SHA-256 of source daily JSON (sorted by date; skip ``_`` temp fields)."""
    hasher = hashlib.sha256()
    for report in sorted(daily_reports, key=lambda r: r.get("date", "")):
        clean = {k: v for k, v in report.items() if not k.startswith("_")}
        hasher.update(json.dumps(clean, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return hasher.hexdigest()[:16]


def load_period_cache(cache_dir: Path, label: str, source_hash: str) -> Optional[dict]:
    """Load a period LLM cache. None = miss or stale source hash."""
    cache_file = cache_dir / f"{label}.json"
    if not cache_file.exists():
        return None
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("_cache_meta", {}).get("source_hash") != source_hash:
        return None
    data.pop("_cache_meta", None)
    print(f"[info] Cache hit ({cache_file.name})")
    return data


def save_period_cache(cache_dir: Path, label: str, result: dict,
                      source_hash: str) -> None:
    cache = {**result, "_cache_meta": {
        "source_hash": source_hash,
        "cached_at": datetime.now().isoformat(),
    }}
    try:
        _atomic_write(cache_dir / f"{label}.json",
                      json.dumps(cache, ensure_ascii=False, indent=2))
    except OSError as e:
        print(f"[warn] Cache write failed: {e}")


def run_cached_period_llm(
    *,
    cache_dir: Path,
    label: str,
    daily_reports: list[dict],
    no_cache: bool,
    force: bool,
    call_llm_fn: Callable[[Optional[Path]], dict],
) -> dict:
    """Cache check → LLM → save global cache → cleanup chunk cache."""
    source_hash = compute_source_hash(daily_reports)
    llm_result = None
    if not no_cache and not force:
        llm_result = load_period_cache(cache_dir, label, source_hash)

    chunk_cache_dir = cache_dir / "chunks" / label
    if llm_result is None:
        if not no_cache:
            chunk_cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            llm_result = call_llm_fn(None if no_cache else chunk_cache_dir)
        except ChunkTimeoutError as e:
            print(f"[error] {e}")
            sys.exit(1)
        save_period_cache(cache_dir, label, llm_result, source_hash)
        _cleanup_chunk_cache(chunk_cache_dir)
    return llm_result


# ─── Chunked LLM ───────────────────────────────────────────────────────

def call_period_summarize_chunked(
    api: str,
    daily_reports: list[dict],
    *,
    summary_prompt: str,
    merge_prompt: str,
    build_config: Callable[[str], LLMCallConfig],
    timeout: int,
    format_reports: Callable[[list[dict]], str],
    make_groups: Callable[[list[dict]], list[list[dict]]],
    target_line: str,
    chunk_cache_dir: Optional[Path] = None,
) -> dict:
    """Single timed call, or group → chunk_text → hierarchical_merge."""
    max_chars = resolved_chunk_chars()
    full_text = format_reports(daily_reports)
    prompt_overhead = len(summary_prompt) + PROMPT_OVERHEAD
    suffix = f"\n\n{target_line}"

    if len(full_text) + prompt_overhead <= max_chars:
        config = build_config(summary_prompt + full_text + suffix)
        return timed_llm_call(api, config, chunk_idx=1, total=1)

    groups = [g for g in make_groups(daily_reports) if g]
    text_groups = [format_reports(g) for g in groups]
    text_chunks = chunk_text(text_groups, max_chars=max_chars - prompt_overhead)

    n = len(text_chunks)
    print(f"[info] {len(full_text):,} chars, split into {n} chunks "
          f"(per-chunk timeout {timeout}s, total ~{timeout * n}s)...")

    global_hash = compute_source_hash(daily_reports) if chunk_cache_dir else None

    partial_summaries = []
    cache_hits = 0
    for i, chunk_texts in enumerate(text_chunks):
        chunk_content = "\n".join(chunk_texts)

        if chunk_cache_dir and global_hash:
            c_hash = hashlib.sha256(chunk_content.encode("utf-8")).hexdigest()[:16]
            cached = _load_chunk_cache(chunk_cache_dir, c_hash, global_hash, n)
            if cached is not None:
                cache_hits += 1
                print(f"[info] Chunk {i+1}/{n} cache hit ({len(chunk_content):,} chars)")
                partial_summaries.append(cached)
                continue

        print(f"[info] Summarizing chunk {i+1}/{n} ({len(chunk_content):,} chars)...")
        config = build_config(summary_prompt + chunk_content + suffix)
        result = timed_llm_call(api, config, chunk_idx=i + 1, total=n)
        partial_summaries.append(result)

        if chunk_cache_dir and global_hash:
            _save_chunk_cache(chunk_cache_dir, c_hash, result, global_hash, n)

    if cache_hits:
        print(f"[info] Chunk cache stats: {cache_hits}/{n} hits, "
              f"{n - cache_hits} API calls")

    if len(partial_summaries) == 1:
        return partial_summaries[0]

    def _merge_config(prompt_text: str) -> LLMCallConfig:
        return build_config(prompt_text)

    return hierarchical_merge(api, partial_summaries, merge_prompt,
                              _merge_config, timeout,
                              cache_dir=chunk_cache_dir / "merges" if chunk_cache_dir else None,
                              cache_context=global_hash or "")


# ─── Chart reshape ─────────────────────────────────────────────────────

def reshape_usage_for_chart(usage_by_source: dict) -> dict:
    chart_input = {}
    for source, summary in (usage_by_source or {}).items():
        totals = summary.get("totals", {})
        if not totals:
            continue
        chart_input[source] = {
            "totals": totals,
            "modelBreakdowns": [{"modelName": n, **v}
                                for n, v in summary.get("model_breakdown", {}).items()],
        }
    return chart_input


def generate_period_chart(usage_by_source: dict, chart_date: date) -> Optional[Path]:
    chart_input = reshape_usage_for_chart(usage_by_source)
    if not chart_input:
        return None
    from .charts import generate_daily_chart
    from common.paths import IMAGES_DIR
    return generate_daily_chart(chart_input, chart_date,
                                output_dir=IMAGES_DIR / "summarize")


def collect_usage_by_source(daily_reports: list[dict]) -> dict:
    from .monthly_summary import aggregate_token_usage
    sources: set[str] = set()
    for r in daily_reports:
        sources.update((r.get("token_usage_by_source") or {}).keys())
        if r.get("token_usage"):
            sources.add("claude_code")
        if r.get("codex_token_usage"):
            sources.add("codex")
    return {s: aggregate_token_usage(daily_reports, source=s) for s in sorted(sources)}


# ─── CLI / argparse ────────────────────────────────────────────────────

def resolve_period_api(args) -> str:
    return getattr(args, "api", None) or _load_config().get("default_api") or DEFAULT_BACKEND


def resolve_reports_dir(args) -> Path:
    return _resolve_output_dir(
        getattr(args, "output", None),
        "SUMMARIZE_REPORTS_DIR",
        "reports_dir",
        DEFAULT_REPORTS_DIR,
    )


def require_hugo_site(args) -> Path:
    hugo_site = resolve_hugo_site(getattr(args, "hugo_site", None))
    if not hugo_site.exists():
        print(f"[error] Hugo site directory not found: {hugo_site}")
        sys.exit(1)
    return hugo_site


def add_api_argument(parser) -> None:
    parser.add_argument(
        "--api", type=str, choices=list(LLM_BACKENDS), default=None,
        help=f"LLM API (default: config default_api, else {DEFAULT_BACKEND})",
    )


def add_generate_arguments(parser, *, timeout_default: int) -> None:
    add_api_argument(parser)
    parser.add_argument("--output", type=str, default=None,
                        help="Reports directory (default: outputs/reports/summarize/)")
    parser.add_argument("--deploy", action="store_true",
                        help="Also deploy to Hugo site")
    parser.add_argument("--no-deploy", dest="deploy", action="store_false",
                        help="Do not deploy (overrides deploy=true in config)")
    parser.add_argument("--hugo-site", type=str, default=str(resolve_hugo_site()),
                        help="Hugo site root directory")
    parser.add_argument("--timeout", type=int, default=timeout_default,
                        help=f"LLM call timeout in seconds (default: {timeout_default})")
    parser.add_argument("--no-cache", action="store_true",
                        help="Skip LLM cache, force re-call API")
    parser.add_argument("--force", action="store_true",
                        help="Ignore existing output, force regeneration")
    parser.add_argument("--overwrite-human", action="store_true",
                        help="DANGEROUS: allow overwriting hand-written site files")


def add_deploy_arguments(parser) -> None:
    parser.add_argument("--output", type=str, default=None,
                        help="Reports directory (default: outputs/reports/summarize/)")
    parser.add_argument("--hugo-site", type=str, default=str(resolve_hugo_site()),
                        help="Hugo site root directory")
    parser.add_argument("--force", action="store_true",
                        help="Redeploy already-deployed reports (backs up first)")
    parser.add_argument("--overwrite-human", action="store_true",
                        help="DANGEROUS: allow overwriting hand-written site files")
