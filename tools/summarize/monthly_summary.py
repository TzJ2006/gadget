#!/usr/bin/env python3
"""AI 对话月度总结工具

读取 reports/ 下所有日报 JSON，调用 LLM 生成结构化月度总结。

用法:
    python summarize/monthly_summary.py generate --month 2026-02
    python summarize/monthly_summary.py generate --month 2026-02 --api anthropic
    python summarize/monthly_summary.py generate --month 2026-02 --deploy
    python summarize/monthly_summary.py generate --month 2026-02 --no-cache
    python summarize/monthly_summary.py generate                    # 默认上个月
    python summarize/monthly_summary.py list
"""

import argparse
import calendar
import json
import sys
from collections import OrderedDict
from datetime import date
from pathlib import Path
from typing import Optional

from common.hugo import run_hugo_update
from common.io import atomic_write as _atomic_write
from common.llm import LLMCallConfig
from common.site_staging import resolve_site_content_dir

from .config import cli_defaults
from .period_report import (
    DEFAULT_BACKEND,
    DEFAULT_REPORTS_DIR as _DEFAULT_REPORTS_DIR,
    TIMEOUT_MONTHLY,
    _LOW_THINKING,
    add_deploy_arguments,
    add_generate_arguments,
    call_period_summarize_chunked,
    collect_usage_by_source,
    compute_source_hash as _compute_source_hash,
    generate_period_chart,
    generate_period_hugo_post,
    load_period_cache,
    period_cache_dir,
    require_hugo_site,
    resolve_period_api,
    resolve_reports_dir,
    resolved_timeout_monthly,
    run_cached_period_llm,
    save_period_cache,
)

# ─── 1. 数据加载 ───────────────────────────────────────────────────

def _parse_month(month_str: Optional[str]) -> tuple[int, int]:
    """解析 YYYY-MM 格式字符串，默认上个月。返回 (year, month)。"""
    if month_str:
        try:
            parts = month_str.split("-")
            return int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            print(f"[error] Invalid month format: {month_str}, expected YYYY-MM")
            sys.exit(1)

    # 默认上个月
    today = date.today()
    if today.month == 1:
        return today.year - 1, 12
    return today.year, today.month - 1


def load_daily_reports(reports_dir: Path, year: int, month: int) -> list[dict]:
    """读取 reports_dir 下所有匹配 YYYY-MM-DD.json 的日报，按日期排序返回。"""
    prefix = f"{year:04d}-{month:02d}-"
    reports = []

    if not reports_dir.exists():
        return reports

    for f in sorted(reports_dir.glob(f"{prefix}*.json")):
        # 跳过月度/周度报告
        if "monthly" in f.stem or "weekly" in f.stem:
            continue
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            data["_source_file"] = str(f)
            reports.append(data)
        except (OSError, json.JSONDecodeError) as e:
            print(f"[warn] Skipping unreadable file {f.name}: {e}")

    return reports


def format_reports_for_llm(daily_reports: list[dict]) -> str:
    """将日报列表格式化为 LLM 输入文本，剥离机械聚合字段。"""
    parts = []
    for report in daily_reports:
        # 深拷贝并剥离机械聚合的字段
        stripped = {k: v for k, v in report.items()
                    if k not in ("token_usage", "codex_token_usage",
                                 "conversation_summaries", "_source_file")}
        day_text = f"\n{'='*60}\nDate: {report.get('date', 'unknown')}\n{'='*60}\n"
        day_text += json.dumps(stripped, ensure_ascii=False, indent=2)
        parts.append(day_text)
    return "\n".join(parts)


def _has_usage_data(summary: Optional[dict]) -> bool:
    """判断 usage summary 是否包含有效数据。"""
    if not summary:
        return False

    totals = summary.get("totals", {})
    if any(totals.get(field, 0) for field in (
        "totalTokens", "totalCost", "inputTokens", "outputTokens",
        "cacheCreationTokens", "cacheReadTokens", "reasoningOutputTokens",
    )):
        return True

    return any(
        day.get("totalTokens", 0) or day.get("totalCost", 0)
        for day in summary.get("daily", [])
    )


def aggregate_token_usage(daily_reports: list[dict],
                          usage_key: str = "token_usage",
                          source: Optional[str] = None) -> dict:
    """机械聚合日报中的 usage 字段，计算总量、日均、峰值、模型分布。

    若给定 source，则从 report['token_usage_by_source'][source] 读取；
    否则回退到 usage_key（向后兼容旧报告）。
    """
    def _get(report):
        if source is not None:
            bs = report.get("token_usage_by_source") or {}
            if source in bs:
                return bs[source] or {}
            if source == "claude_code":
                return report.get("token_usage", {}) or {}
            if source == "codex":
                return report.get("codex_token_usage", {}) or {}
            return {}
        return report.get(usage_key, {}) or {}

    daily_stats = []
    model_totals = {}  # modelName -> {inputTokens, outputTokens, ..., cost}

    for report in daily_reports:
        tu = _get(report)
        totals = tu.get("totals", {})
        report_date = report.get("date", "unknown")

        tokens = totals.get("totalTokens", 0)
        cost = totals.get("totalCost", 0)

        daily_stats.append({
            "date": report_date,
            "totalTokens": tokens,
            "totalCost": round(cost, 2),
            "inputTokens": totals.get("inputTokens", 0),
            "outputTokens": totals.get("outputTokens", 0),
            "cacheCreationTokens": totals.get("cacheCreationTokens", 0),
            "cacheReadTokens": totals.get("cacheReadTokens", 0),
            "reasoningOutputTokens": totals.get("reasoningOutputTokens", 0),
        })

        # 模型分布
        breakdowns = tu.get("modelBreakdowns", [])
        if not breakdowns:
            for day in tu.get("daily", []):
                breakdowns = day.get("modelBreakdowns", [])
                if breakdowns:
                    break

        for mb in breakdowns:
            name = mb.get("modelName", "unknown")
            if name not in model_totals:
                model_totals[name] = {"inputTokens": 0, "outputTokens": 0,
                                      "cacheCreationTokens": 0, "cacheReadTokens": 0,
                                      "reasoningOutputTokens": 0,
                                      "cost": 0.0}
            for field in ("inputTokens", "outputTokens", "cacheCreationTokens",
                          "cacheReadTokens", "reasoningOutputTokens"):
                model_totals[name][field] += mb.get(field, 0)
            model_totals[name]["cost"] += mb.get("cost", 0)

    # 汇总
    total_tokens = sum(d["totalTokens"] for d in daily_stats)
    total_cost = sum(d["totalCost"] for d in daily_stats)
    active_days = [d for d in daily_stats if d["totalTokens"] > 0]
    peak_day = max(daily_stats, key=lambda d: d["totalCost"]) if daily_stats else None

    return {
        "daily": daily_stats,
        "totals": {
            "totalTokens": total_tokens,
            "totalCost": round(total_cost, 2),
            "inputTokens": sum(d["inputTokens"] for d in daily_stats),
            "outputTokens": sum(d["outputTokens"] for d in daily_stats),
            "cacheCreationTokens": sum(d["cacheCreationTokens"] for d in daily_stats),
            "cacheReadTokens": sum(d["cacheReadTokens"] for d in daily_stats),
            "reasoningOutputTokens": sum(d["reasoningOutputTokens"] for d in daily_stats),
        },
        "daily_average_cost": round(total_cost / len(active_days), 2) if active_days else 0,
        "daily_average_tokens": round(total_tokens / len(active_days)) if active_days else 0,
        "peak_day": peak_day,
        "model_breakdown": {name: {**v, "cost": round(v["cost"], 2)}
                            for name, v in sorted(model_totals.items(),
                                                  key=lambda x: -x[1]["cost"])},
    }


def combine_usage_summaries(*summaries: dict) -> dict:
    """合并多个 usage summary，用于月度总览和图表。"""
    daily_by_date = {}
    model_totals = {}

    for summary in summaries:
        if not _has_usage_data(summary):
            continue

        for day in summary.get("daily", []):
            day_date = day.get("date")
            if not day_date:
                continue
            bucket = daily_by_date.setdefault(day_date, {
                "date": day_date,
                "totalTokens": 0,
                "totalCost": 0.0,
                "inputTokens": 0,
                "outputTokens": 0,
                "cacheCreationTokens": 0,
                "cacheReadTokens": 0,
                "reasoningOutputTokens": 0,
            })
            for field in ("totalTokens", "inputTokens", "outputTokens",
                          "cacheCreationTokens", "cacheReadTokens",
                          "reasoningOutputTokens"):
                bucket[field] += day.get(field, 0)
            bucket["totalCost"] += day.get("totalCost", 0)

        for name, info in summary.get("model_breakdown", {}).items():
            bucket = model_totals.setdefault(name, {
                "inputTokens": 0,
                "outputTokens": 0,
                "cacheCreationTokens": 0,
                "cacheReadTokens": 0,
                "reasoningOutputTokens": 0,
                "cost": 0.0,
            })
            for field in ("inputTokens", "outputTokens", "cacheCreationTokens",
                          "cacheReadTokens", "reasoningOutputTokens"):
                bucket[field] += info.get(field, 0)
            bucket["cost"] += info.get("cost", 0)

    if not daily_by_date and not model_totals:
        return {}

    daily_stats = []
    for day_date in sorted(daily_by_date):
        day = daily_by_date[day_date]
        day["totalCost"] = round(day["totalCost"], 2)
        daily_stats.append(day)

    total_tokens = sum(d["totalTokens"] for d in daily_stats)
    total_cost = sum(d["totalCost"] for d in daily_stats)
    active_days = [d for d in daily_stats if d["totalTokens"] > 0]
    peak_day = max(daily_stats, key=lambda d: d["totalCost"]) if daily_stats else None

    return {
        "daily": daily_stats,
        "totals": {
            "totalTokens": total_tokens,
            "totalCost": round(total_cost, 2),
            "inputTokens": sum(d["inputTokens"] for d in daily_stats),
            "outputTokens": sum(d["outputTokens"] for d in daily_stats),
            "cacheCreationTokens": sum(d["cacheCreationTokens"] for d in daily_stats),
            "cacheReadTokens": sum(d["cacheReadTokens"] for d in daily_stats),
            "reasoningOutputTokens": sum(d["reasoningOutputTokens"] for d in daily_stats),
        },
        "daily_average_cost": round(total_cost / len(active_days), 2) if active_days else 0,
        "daily_average_tokens": round(total_tokens / len(active_days)) if active_days else 0,
        "peak_day": peak_day,
        "model_breakdown": {
            name: {**info, "cost": round(info["cost"], 2)}
            for name, info in sorted(model_totals.items(), key=lambda x: -x[1]["cost"])
        },
    }


def compute_statistics(daily_reports: list[dict], year: int, month: int) -> dict:
    """机械计算统计信息：对话数、任务完成数、活跃天数、项目列表等。"""
    total_days = calendar.monthrange(year, month)[1]
    active_dates = set()
    total_conversations = 0
    tasks_completed = 0
    tasks_in_progress = 0
    projects = set()

    for report in daily_reports:
        report_date = report.get("date", "")
        if report_date:
            active_dates.add(report_date)

        # 对话数从 conversation_summaries 计
        convs = report.get("conversation_summaries", [])
        total_conversations += len(convs)

        for cs in convs:
            proj = cs.get("project", "")
            if proj:
                projects.add(proj)

        for task in report.get("tasks", []):
            status = task.get("status", "")
            if status == "completed":
                tasks_completed += 1
            elif status == "in_progress":
                tasks_in_progress += 1

    return {
        "total_days": total_days,
        "active_days": len(active_dates),
        "total_conversations": total_conversations,
        "tasks_completed": tasks_completed,
        "tasks_in_progress": tasks_in_progress,
        "projects": sorted(projects),
        "project_count": len(projects),
    }


# ─── 2. LLM 调用 ──────────────────────────────────────────────────

MONTHLY_SUMMARY_PROMPT = """You are a professional monthly summary analyst. Below are daily AI conversation reports \
(JSON format) for an entire month. Analyze the work patterns and trends across the month to produce a structured monthly summary.

Requirements:
1. Distill trends and patterns from a whole-month perspective; do not simply list each day's content
2. project_overview sorted by days_active descending; identify key milestones
3. key_achievements: keep only the 5-10 most important items for the month (importance >= 7)
4. recurring_problems: identify problem patterns that recur across multiple days; analyze root causes
5. ai_collaboration_trends: distill trends from human_vs_ai and ai_limitations
6. learnings_digest: deduplicate and merge, group by category, keep only the most valuable learnings
7. Use English

Return the following JSON structure:

```json
{
    "month": "YYYY-MM",
    "summary": "One-paragraph summary of the month",
    "project_overview": [
        {
            "project": "Project Name",
            "days_active": 15,
            "key_milestones": ["Milestone 1", "Milestone 2"],
            "status": "active | completed | paused",
            "description": "Overview of the project's progress this month"
        }
    ],
    "key_achievements": [
        {
            "title": "Achievement title",
            "date": "YYYY-MM-DD",
            "description": "Detailed description",
            "project": "Related project",
            "importance": 10
        }
    ],
    "recurring_problems": [
        {
            "pattern": "Description of the problem pattern",
            "occurrences": 5,
            "dates": ["YYYY-MM-DD"],
            "root_cause": "Root cause analysis",
            "resolution_status": "resolved | ongoing | workaround"
        }
    ],
    "ai_collaboration_trends": {
        "human_initiated_insights": 12,
        "ai_limitation_patterns": ["Pattern 1"],
        "improvement_areas": ["Improvement area 1"]
    },
    "learnings_digest": [
        {
            "category": "architecture | debugging | tools | domain",
            "content": "Learning content",
            "source_dates": ["YYYY-MM-DD"],
            "importance": 9
        }
    ]
}
```

Return JSON only, no additional text.

Daily report data:
"""

MONTHLY_MERGE_PROMPT = """You are a professional monthly summary analyst. Below are independent monthly summaries \
(JSON format) from multiple segments of the same month. Merge them into a single complete monthly summary.

Requirements:
1. Merge all project_overview entries; combine days_active and key_milestones for the same project
2. Merge key_achievements; deduplicate, keep only the 5-10 most important items
3. Merge recurring_problems; combine occurrences and dates for the same pattern
4. Merge all fields of ai_collaboration_trends
5. Merge learnings_digest; deduplicate and merge, group by category
6. Generate a one-paragraph summary for the entire month
7. Return the same JSON structure as each segment
8. Use English
9. Return JSON only, no additional text

"""


def _monthly_tool_schema() -> list[dict]:
    """返回 Anthropic tool use schema for submit_monthly_report。"""
    return [{
        "name": "submit_monthly_report",
        "description": "Submit a structured monthly summary report",
        "input_schema": {
            "type": "object",
            "properties": {
                "month": {"type": "string"},
                "summary": {"type": "string"},
                "project_overview": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string"},
                        "days_active": {"type": "integer"},
                        "key_milestones": {"type": "array", "items": {"type": "string"}},
                        "status": {"type": "string", "enum": ["active", "completed", "paused"]},
                        "description": {"type": "string"},
                    },
                    "required": ["project", "days_active", "status", "description"],
                }},
                "key_achievements": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "date": {"type": "string"},
                        "description": {"type": "string"},
                        "project": {"type": "string"},
                        "importance": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                    "required": ["title", "description", "importance"],
                }},
                "recurring_problems": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string"},
                        "occurrences": {"type": "integer"},
                        "dates": {"type": "array", "items": {"type": "string"}},
                        "root_cause": {"type": "string"},
                        "resolution_status": {"type": "string",
                                              "enum": ["resolved", "ongoing", "workaround"]},
                    },
                    "required": ["pattern", "occurrences", "root_cause", "resolution_status"],
                }},
                "ai_collaboration_trends": {"type": "object", "properties": {
                    "human_initiated_insights": {"type": "integer"},
                    "ai_limitation_patterns": {"type": "array", "items": {"type": "string"}},
                    "improvement_areas": {"type": "array", "items": {"type": "string"}},
                }},
                "learnings_digest": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string",
                                     "enum": ["architecture", "debugging", "tools", "domain"]},
                        "content": {"type": "string"},
                        "source_dates": {"type": "array", "items": {"type": "string"}},
                        "importance": {"type": "integer", "minimum": 1, "maximum": 10},
                    },
                    "required": ["category", "content", "importance"],
                }},
            },
            "required": ["month", "summary", "project_overview", "key_achievements"],
        },
    }]


def _build_monthly_config(prompt_text: str, timeout: int = TIMEOUT_MONTHLY) -> LLMCallConfig:
    """构建月度专用的 LLMCallConfig。"""
    return LLMCallConfig(
        prompt=prompt_text,
        timeout=timeout,
        anthropic_tools=_monthly_tool_schema(),
        anthropic_tool_name="submit_monthly_report",
        thinking=_LOW_THINKING,
    )


def _monthly_report_groups(daily_reports: list[dict]) -> list[list[dict]]:
    return [daily_reports[i:i + 7] for i in range(0, len(daily_reports), 7)]


def _call_monthly_summarize_chunked(api: str, daily_reports: list[dict],
                                    month_str: str, timeout: int = TIMEOUT_MONTHLY,
                                    chunk_cache_dir: Optional[Path] = None) -> dict:
    """分块调用 LLM 生成月度总结（当内容超过 chunk 上限时自动分组）。"""
    return call_period_summarize_chunked(
        api, daily_reports,
        summary_prompt=MONTHLY_SUMMARY_PROMPT,
        merge_prompt=MONTHLY_MERGE_PROMPT,
        build_config=lambda prompt_text: _build_monthly_config(prompt_text, timeout),
        timeout=timeout,
        format_reports=format_reports_for_llm,
        make_groups=_monthly_report_groups,
        target_line=f"Target month: {month_str}",
        chunk_cache_dir=chunk_cache_dir,
    )


# ─── 3. 图表生成 ───────────────────────────────────────────────────

def _generate_chart(usage_by_source: dict, year: int, month: int) -> Optional[Path]:
    """生成月报 usage 图表（单 PNG 三子图，按来源）。"""
    return generate_period_chart(usage_by_source, date(year, month, 1))


# ─── 4. 输出渲染 ───────────────────────────────────────────────────

def generate_monthly_markdown(report: dict, year: int, month: int,
                              chart_filename: Optional[str] = None) -> str:
    """将结构化月度报告渲染为 Markdown。"""
    month_str = f"{year:04d}-{month:02d}"
    lines = []
    lines.append(f"# Monthly Summary — {month_str}\n")

    # 一段话总结
    if report.get("summary"):
        lines.append(f"> {report['summary']}\n")

    # ── 本月概览 ──
    stats = report.get("statistics", {})
    token_summary = report.get("token_usage_summary", {})
    codex_summary = report.get("codex_token_usage_summary", {})
    combined_summary = report.get("combined_token_usage_summary", {})
    if not _has_usage_data(combined_summary):
        combined_summary = combine_usage_summaries(token_summary, codex_summary)
    totals = combined_summary.get("totals", {})
    has_claude_usage = _has_usage_data(token_summary)
    has_codex_usage = _has_usage_data(codex_summary)

    lines.append("## Monthly Overview\n")
    lines.append("| Metric | Value |")
    lines.append("|------|------|")
    total_days = stats.get("total_days", calendar.monthrange(year, month)[1])
    lines.append(f"| Active Days | {stats.get('active_days', 0)} / {total_days} |")
    lines.append(f"| Total Conversations | {stats.get('total_conversations', 0)} |")
    lines.append(f"| Projects | {stats.get('project_count', 0)} |")
    lines.append(f"| Tasks Completed | {stats.get('tasks_completed', 0)} |")
    lines.append(f"| Tasks In Progress | {stats.get('tasks_in_progress', 0)} |")
    if _has_usage_data(combined_summary):
        total_tokens = totals.get("totalTokens", 0)
        total_cost = totals.get("totalCost", 0)
        lines.append(f"| Total Tokens | {total_tokens:,} |")
        lines.append(f"| Total Cost | ${total_cost:,.2f} |")
        if has_claude_usage and has_codex_usage:
            claude_totals = token_summary.get("totals", {})
            codex_totals = codex_summary.get("totals", {})
            lines.append(f"| Claude Code Token | {claude_totals.get('totalTokens', 0):,} |")
            lines.append(f"| Claude Code Cost | ${claude_totals.get('totalCost', 0):,.2f} |")
            lines.append(f"| Codex Tokens | {codex_totals.get('totalTokens', 0):,} |")
            lines.append(f"| Codex Cost | ${codex_totals.get('totalCost', 0):,.2f} |")
        daily_avg_cost = combined_summary.get("daily_average_cost", 0)
        if daily_avg_cost:
            lines.append(f"| Daily Average Cost | ${daily_avg_cost:,.2f} |")
    lines.append("")

    # ── 项目进展 ──
    projects = report.get("project_overview", [])
    if projects:
        lines.append("## Project Progress\n")
        for p in projects:
            status_label = {"active": "🔄 active", "completed": "✅ completed",
                            "paused": "⏸️ paused"}.get(p.get("status", ""), p.get("status", ""))
            lines.append(f"### {p.get('project', '(unknown)')} ({p.get('days_active', '?')} days active) — {status_label}\n")
            if p.get("description"):
                lines.append(f"{p['description']}\n")
            milestones = p.get("key_milestones", [])
            if milestones:
                lines.append(f"**Key Milestones:**")
                for m in milestones:
                    lines.append(f"- {m}")
                lines.append("")

    # ── 本月关键成就 ──
    achievements = report.get("key_achievements", [])
    if achievements:
        lines.append("## Key Achievements\n")
        for i, a in enumerate(achievements, 1):
            date_str = f"{a['date']}, " if a.get("date") else ""
            proj_str = f"{a['project']}" if a.get("project") else ""
            meta = f" ({date_str}{proj_str})" if (date_str or proj_str) else ""
            lines.append(f"{i}. **{a.get('title', '(untitled)')}**{meta} — {a.get('description', '')}")
        lines.append("")

    # ── 反复出现的问题 ──
    problems = report.get("recurring_problems", [])
    if problems:
        lines.append("## Recurring Problems\n")
        status_icons = {"resolved": "✅ Resolved", "ongoing": "🔄 Ongoing",
                        "workaround": "🔧 Workaround"}
        for i, p in enumerate(problems, 1):
            lines.append(f"### {i}. {p.get('pattern', '(unknown)')} ({p.get('occurrences', '?')} occurrences)\n")
            dates_str = ", ".join(p.get("dates", [])) if p.get("dates") else "—"
            lines.append(f"**Dates:** {dates_str}")
            lines.append(f"**Root Cause:** {p.get('root_cause', '—')}")
            status = status_icons.get(p.get("resolution_status", ""),
                                      p.get("resolution_status", "—"))
            lines.append(f"**Status:** {status}\n")

    # ── 人机协作趋势 ──
    ai_trends = report.get("ai_collaboration_trends", {})
    if ai_trends:
        lines.append("## Human-AI Collaboration Trends\n")
        if isinstance(ai_trends, dict):
            insights = ai_trends.get("human_initiated_insights", 0)
            if insights:
                lines.append(f"- **Human-initiated insights:** {insights} items")
            for pattern in ai_trends.get("ai_limitation_patterns", []):
                lines.append(f"- **AI limitation patterns:** {pattern}")
            for area in ai_trends.get("improvement_areas", []):
                lines.append(f"- **Improvement areas:** {area}")
        else:
            # Off-schema LLM output (list/str) — render as plain bullets
            # instead of crashing after the whole LLM pipeline succeeded.
            for item in ai_trends if isinstance(ai_trends, list) else [ai_trends]:
                lines.append(f"- {item}")
        lines.append("")

    # ── 本月收获精选 ──
    learnings = report.get("learnings_digest", [])
    if learnings:
        lines.append("## Monthly Learnings Digest\n")
        # 按 category 分组
        by_cat = OrderedDict()
        cat_labels = {"architecture": "Architecture", "debugging": "Debugging",
                      "tools": "Tools", "domain": "Domain Knowledge"}
        for l in learnings:
            cat = l.get("category", "other")
            by_cat.setdefault(cat, []).append(l)
        for cat, items in by_cat.items():
            label = cat_labels.get(cat, cat)
            lines.append(f"### {label} ({cat})\n")
            for item in items:
                source = ", ".join(item.get("source_dates", [])) if item.get("source_dates") else ""
                source_str = f" (Source: {source})" if source else ""
                lines.append(f"- {item.get('content', '')}{source_str}")
            lines.append("")

    # ── Token 用量统计 ──
    if _has_usage_data(combined_summary):
        lines.append("## Token Usage Statistics\n")

        from .usage_card import render_usage_card
        by_source = (report.get("token_usage_by_source_summary")
                     or {"claude_code": token_summary, "codex": codex_summary})
        card = render_usage_card(by_source, f"AI Usage · {month_str}")
        if card:
            lines.append(card + "\n")

        peak = combined_summary.get("peak_day")
        if peak:
            lines.append(f"**Peak Day:** {peak['date']} — "
                         f"${peak['totalCost']:.2f} / "
                         f"{peak['totalTokens']/1_000_000:.1f}M tokens\n")

        daily_avg = combined_summary.get("daily_average_cost", 0)
        if daily_avg:
            lines.append(f"**Daily Average:** ${daily_avg:.2f}\n")

    return "\n".join(lines)


def generate_monthly_hugo_post(markdown_body: str, year: int, month: int,
                               hugo_site: Path,
                               chart_path: Optional[Path] = None,
                               api: str = DEFAULT_BACKEND,
                               force: bool = False,
                               overwrite_human: bool = False) -> Path:
    """将月度总结渲染为 Hugo bugJournal 格式并写入 staging content 目录（双语）。"""
    month_str = f"{year:04d}-{month:02d}"
    last_day = calendar.monthrange(year, month)[1]
    return generate_period_hugo_post(
        markdown_body, hugo_site,
        title=f"Monthly Summary {month_str}",
        post_date=date(year, month, last_day),
        hour=23, minute=59, second=0,
        keywords=["Bug Journal", "Monthly Summary"],
        fallback_summary=f"{month_str} Monthly AI conversation summary",
        content_parts=("bugJournal", "monthly"),
        filename=f"{month_str}-monthly.md",
        chart_path=chart_path,
        chart_image_subdir="monthly",
        api=api, force=force, overwrite_human=overwrite_human,
    )


def save_monthly_report(report: dict, markdown: str, year: int, month: int,
                        output_dir: Path) -> tuple[Path, Path]:
    """保存月度报告的 Markdown 和 JSON。"""
    month_str = f"{year:04d}-{month:02d}"
    output_dir.mkdir(parents=True, exist_ok=True)

    md_path = output_dir / f"{month_str}-monthly.md"
    json_path = output_dir / f"{month_str}-monthly.json"

    from .backup import backup_existing
    backup_existing(md_path, json_path)

    _atomic_write(md_path, markdown)
    print(f"[ok] Monthly Markdown saved: {md_path}")

    _atomic_write(json_path, json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[ok] Monthly JSON saved: {json_path}")

    return md_path, json_path


# ─── 5. 缓存 ──────────────────────────────────────────────────────

def _cache_dir(reports_dir: Path) -> Path:
    return period_cache_dir("monthly")


def _load_monthly_cache(reports_dir: Path, year: int, month: int,
                        source_hash: str) -> Optional[dict]:
    """加载月度缓存。返回 None 表示未命中。"""
    return load_period_cache(
        _cache_dir(reports_dir), f"{year:04d}-{month:02d}", source_hash)


def _save_monthly_cache(reports_dir: Path, year: int, month: int,
                        result: dict, source_hash: str) -> None:
    """保存月度缓存（附带源哈希用于失效检测）。"""
    save_period_cache(
        _cache_dir(reports_dir), f"{year:04d}-{month:02d}", result, source_hash)



# 分段缓存 → llm_backends.py (_load_chunk_cache, _save_chunk_cache, _cleanup_chunk_cache)


# ─── 6. CLI 命令 ──────────────────────────────────────────────────

def cmd_generate(args):
    """生成月度总结：load → format → LLM → aggregate → markdown → save → deploy。"""
    year, month = _parse_month(args.month)
    month_str = f"{year:04d}-{month:02d}"
    print(f"[info] Target month: {month_str}")

    api = resolve_period_api(args)
    reports_dir = resolve_reports_dir(args)

    # 检查已有输出
    force = getattr(args, "force", False)
    no_cache = getattr(args, "no_cache", False)
    existing_json = reports_dir / f"{month_str}-monthly.json"

    # 定型检查：过去的月份（月份 < 当前月份）视为 finalized
    today = date.today()
    is_past_month = (year < today.year) or (year == today.year and month < today.month)

    if existing_json.exists() and not force and not no_cache:
        # 检查是否已标记 finalized
        try:
            with open(existing_json, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
            if existing_data.get("_finalized") and is_past_month:
                print(f"[info] Monthly report finalized: {existing_json}")
                print(f"[info] Use --force to regenerate")
                return
        except (OSError, json.JSONDecodeError):
            pass
        print(f"[info] Monthly report already exists: {existing_json}")
        print(f"[info] Use --force to regenerate, or --no-cache to skip LLM cache")
        return

    # 加载日报
    daily_reports = load_daily_reports(reports_dir, year, month)
    if not daily_reports:
        print(f"[warn] No daily reports found for {month_str} (in {reports_dir})")
        sys.exit(0)
    print(f"[info] Loaded {len(daily_reports)} daily reports")

    timeout = getattr(args, "timeout", TIMEOUT_MONTHLY)
    llm_result = run_cached_period_llm(
        cache_dir=_cache_dir(reports_dir),
        label=month_str,
        daily_reports=daily_reports,
        no_cache=no_cache,
        force=force,
        call_llm_fn=lambda chunk_dir: _call_monthly_summarize_chunked(
            api, daily_reports, month_str, timeout=timeout,
            chunk_cache_dir=chunk_dir),
    )

    usage_by_source = collect_usage_by_source(daily_reports)
    combined_token_usage = combine_usage_summaries(*usage_by_source.values())
    statistics = compute_statistics(daily_reports, year, month)

    # 组装最终报告
    report = {
        "month": month_str,
        **llm_result,
        "statistics": statistics,
        "token_usage_by_source_summary": usage_by_source,
        "token_usage_summary": usage_by_source.get("claude_code", {}),
        "codex_token_usage_summary": usage_by_source.get("codex", {}),
        "combined_token_usage_summary": combined_token_usage,
    }

    # 标记定型状态
    if is_past_month:
        report["_finalized"] = True

    # 渲染 Markdown（usage 卡片内嵌，无需图表文件）
    markdown = generate_monthly_markdown(report, year, month)

    # 保存
    save_monthly_report(report, markdown, year, month, reports_dir)

    # Hugo 部署
    if getattr(args, "deploy", False):
        hugo_site = require_hugo_site(args)

        generate_monthly_hugo_post(markdown, year, month, hugo_site,
                                   api=args.api, force=force,
                                   overwrite_human=getattr(args, "overwrite_human", False))

        run_hugo_update(hugo_site)

    print(f"\n[ok] Monthly summary generation complete: {month_str}")


def cmd_deploy(args):
    """Replay-deploy saved monthly reports to Hugo — no LLM re-run.

    Deployed-state = same-named file present in the Hugo content dir; --force
    redeploys (backing the previous file up to outputs/backups/website-force/)."""
    reports_dir = resolve_reports_dir(args)
    hugo_site = require_hugo_site(args)

    if getattr(args, "month", None):
        md_files = [reports_dir / f"{args.month}-monthly.md"]
        md_files = [f for f in md_files if f.exists()]
        if not md_files:
            print(f"[warn] Monthly report not found: {args.month}")
            sys.exit(0)
    else:
        md_files = sorted(reports_dir.glob("*-monthly.md"))
        if not md_files:
            print(f"[warn] No monthly report .md files in {reports_dir}")
            sys.exit(0)

    staged_dir = resolve_site_content_dir(hugo_site, "bugJournal", "monthly")
    deployed = {p.stem for p in staged_dir.glob("*-monthly.md")}
    force = getattr(args, "force", False)
    to_deploy = [f for f in md_files if force or f.stem not in deployed]

    print(f"[info] Monthly reports: {len(md_files)}, deployed: "
          f"{len(md_files) - len(to_deploy)}, pending: {len(to_deploy)}")
    if not to_deploy:
        print("[ok] All monthly reports already deployed")
        return

    from common.paths import IMAGES_DIR
    for md_file in to_deploy:
        month_str = md_file.stem[:-len("-monthly")]
        year, month = int(month_str[:4]), int(month_str[5:7])
        chart = IMAGES_DIR / "summarize" / f"{date(year, month, 1).isoformat()}-usage.png"
        generate_monthly_hugo_post(
            md_file.read_text(encoding="utf-8"), year, month, hugo_site,
            chart_path=chart if chart.exists() else None,
            force=force,
            overwrite_human=getattr(args, "overwrite_human", False))

    run_hugo_update(hugo_site)


def cmd_list(args):
    """列出所有可用月份及其日报数量。"""
    reports_dir = resolve_reports_dir(args)

    if not reports_dir.exists():
        print(f"[warn] Reports directory not found: {reports_dir}")
        return

    # 按月分组
    months = {}
    for f in sorted(reports_dir.glob("????-??-??.json")):
        if "monthly" in f.stem or "weekly" in f.stem:
            continue
        month_key = f.stem[:7]  # YYYY-MM
        months.setdefault(month_key, []).append(f.stem)

    if not months:
        print("[info] No daily report files found")
        return

    print(f"{'Month':<12} {'Reports':>7}  {'Monthly':>8}")
    print("-" * 34)
    for month_key in sorted(months):
        count = len(months[month_key])
        monthly_exists = (reports_dir / f"{month_key}-monthly.json").exists()
        marker = "  ✅" if monthly_exists else ""
        print(f"{month_key:<12} {count:>7}  {marker}")

    print(f"\nTotal: {len(months)} months, {sum(len(v) for v in months.values())} daily reports")


def main():
    parser = argparse.ArgumentParser(description="AI Conversation Monthly Summary Tool")
    subparsers = parser.add_subparsers(dest="command")

    # ── generate 子命令 ──
    sp_gen = subparsers.add_parser("generate", help="Generate monthly summary")
    sp_gen.add_argument("--month", type=str, default=None,
                        help="Target month (YYYY-MM), defaults to last month")
    add_generate_arguments(sp_gen, timeout_default=resolved_timeout_monthly())
    sp_gen.set_defaults(**cli_defaults())

    sp_dep = subparsers.add_parser(
        "deploy", help="Replay-deploy saved monthly reports to Hugo (no LLM re-run)")
    sp_dep.add_argument("--month", type=str, default=None,
                        help="Deploy a specific month (YYYY-MM); default: all pending")
    add_deploy_arguments(sp_dep)
    sp_dep.set_defaults(**cli_defaults())

    # ── list 子命令 ──
    sp_list = subparsers.add_parser("list", help="List available months and report counts")
    sp_list.add_argument("--output", type=str, default=None,
                         help="Reports directory (default: outputs/reports/summarize/)")

    args = parser.parse_args()

    if args.command == "generate":
        cmd_generate(args)
    elif args.command == "deploy":
        cmd_deploy(args)
    elif args.command == "list":
        cmd_list(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
