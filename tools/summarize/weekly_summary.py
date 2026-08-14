#!/usr/bin/env python3
"""AI 对话周报总结工具

读取 reports/ 下指定 ISO 周的日报 JSON，调用 LLM 生成结构化周报。

用法:
    python summarize/weekly_summary.py generate --week 2026-W12
    python summarize/weekly_summary.py generate --week 2026-W12 --api anthropic
    python summarize/weekly_summary.py generate --week 2026-W12 --deploy
    python summarize/weekly_summary.py generate --week 2026-W12 --no-cache
    python summarize/weekly_summary.py generate                    # 默认上一周
    python summarize/weekly_summary.py list
"""

import argparse
import json
import sys
from collections import OrderedDict
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from common.hugo import run_hugo_update
from common.io import atomic_write as _atomic_write
from common.llm import LLMCallConfig
from common.site_staging import resolve_site_content_dir

from .config import cli_defaults
from .monthly_summary import (
    format_reports_for_llm,
    combine_usage_summaries,
    _has_usage_data,
)
from .period_report import (
    DEFAULT_BACKEND,
    DEFAULT_REPORTS_DIR as _DEFAULT_REPORTS_DIR,
    TIMEOUT_WEEKLY,
    _LOW_THINKING,
    add_deploy_arguments,
    add_generate_arguments,
    call_period_summarize_chunked,
    collect_usage_by_source,
    generate_period_chart,
    generate_period_hugo_post,
    load_period_cache,
    period_cache_dir,
    require_hugo_site,
    resolve_period_api,
    resolve_reports_dir,
    resolved_timeout_weekly,
    run_cached_period_llm,
    save_period_cache,
)





# ─── 1. 周解析与日报加载 ─────────────────────────────────────────────

def _parse_week(week_str: Optional[str]) -> tuple[int, int]:
    """解析 YYYY-WNN 格式字符串，默认上一周。返回 (iso_year, iso_week)。"""
    if week_str:
        try:
            parts = week_str.upper().split("-W")
            if len(parts) != 2:
                raise ValueError
            iso_year = int(parts[0])
            iso_week = int(parts[1])
            # 验证有效性
            date.fromisocalendar(iso_year, iso_week, 1)
            return iso_year, iso_week
        except (ValueError, IndexError, OverflowError):
            print(f"[error] 无效的周格式: {week_str}，期望 YYYY-WNN (如 2026-W12)")
            sys.exit(1)

    # 默认上一周
    last_week = date.today() - timedelta(weeks=1)
    iso_year, iso_week, _ = last_week.isocalendar()
    return iso_year, iso_week


def _week_date_range(iso_year: int, iso_week: int) -> tuple[date, date]:
    """返回 ISO 周的 (周一, 周日) 日期。"""
    monday = date.fromisocalendar(iso_year, iso_week, 1)
    sunday = date.fromisocalendar(iso_year, iso_week, 7)
    return monday, sunday


def _week_str(iso_year: int, iso_week: int) -> str:
    """格式化为 YYYY-WNN。"""
    return f"{iso_year:04d}-W{iso_week:02d}"


def load_weekly_reports(reports_dir: Path, iso_year: int,
                        iso_week: int) -> list[dict]:
    """读取 reports_dir 下属于指定 ISO 周的日报 JSON，按日期排序返回。"""
    monday, sunday = _week_date_range(iso_year, iso_week)
    reports = []

    if not reports_dir.exists():
        return reports

    current = monday
    while current <= sunday:
        json_file = reports_dir / f"{current.isoformat()}.json"
        if json_file.exists():
            try:
                with open(json_file, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                data["_source_file"] = str(json_file)
                reports.append(data)
            except (OSError, json.JSONDecodeError) as e:
                print(f"[warn] 跳过无法读取的文件 {json_file.name}: {e}")
        current += timedelta(days=1)

    return reports


def compute_weekly_statistics(daily_reports: list[dict], iso_year: int,
                              iso_week: int) -> dict:
    """机械计算周统计信息：对话数、任务完成数、活跃天数、项目列表等。"""
    active_dates = set()
    total_conversations = 0
    tasks_completed = 0
    tasks_in_progress = 0
    projects = set()

    for report in daily_reports:
        report_date = report.get("date", "")
        if report_date:
            active_dates.add(report_date)

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

    monday, sunday = _week_date_range(iso_year, iso_week)
    return {
        "total_days": 7,
        "date_range": {"start": monday.isoformat(), "end": sunday.isoformat()},
        "active_days": len(active_dates),
        "total_conversations": total_conversations,
        "tasks_completed": tasks_completed,
        "tasks_in_progress": tasks_in_progress,
        "projects": sorted(projects),
        "project_count": len(projects),
    }


# ─── 2. LLM 调用 ────────────────────────────────────────────────────

WEEKLY_SUMMARY_PROMPT = """You are a professional weekly report analyst. Below are the daily AI conversation reports \
for one week (JSON format). Please analyze this week's work progress and problem resolution, and generate a structured weekly report.

Requirements:
1. Aggregate progress from a weekly perspective; do not list day by day
2. project_progress sorted by days_active descending, with status for each project
3. key_tasks should only include important tasks with importance >= 6
4. problems_resolved should pair problems with their solutions
5. learnings should be deduplicated, merged, and grouped by category
6. next_week_outlook should infer next week's priorities based on incomplete tasks and ongoing projects
7. Use English

Please return the following JSON structure:

```json
{
    "week": "YYYY-WNN",
    "summary": "One-paragraph summary of the week",
    "project_progress": [
        {
            "project": "Project name",
            "days_active": 5,
            "accomplishments": ["Accomplishment 1"],
            "blockers": ["Blocker 1"],
            "status": "active | completed | paused"
        }
    ],
    "key_tasks": [
        {
            "title": "Task title",
            "date": "YYYY-MM-DD",
            "status": "completed | in_progress | blocked",
            "description": "Description",
            "importance": 8
        }
    ],
    "problems_resolved": [
        {
            "problem": "Problem description",
            "solution": "Solution",
            "date": "YYYY-MM-DD",
            "project": "Related project"
        }
    ],
    "learnings": [
        {
            "category": "architecture | debugging | tools | domain",
            "content": "Learning content",
            "importance": 8
        }
    ],
    "ai_usage_notes": {
        "effective_patterns": ["Effective pattern 1"],
        "limitations_encountered": ["Limitation 1"]
    },
    "next_week_outlook": "Next week outlook/plan"
}
```

Return JSON only, no additional text.

Daily report data:
"""

WEEKLY_MERGE_PROMPT = """You are a professional weekly report analyst. Below are multiple independent weekly report \
summaries for the same week (JSON format). Please merge them into one complete weekly report.

Requirements:
1. Merge all project_progress; combine days_active and accomplishments for the same project
2. Merge key_tasks, deduplicate, keep only the most important ones
3. Merge problems_resolved, deduplicate
4. Merge learnings, deduplicate and group by category
5. Merge all fields of ai_usage_notes
6. Generate a one-paragraph summary for the entire week
7. Generate next_week_outlook based on the merged information
8. Return the same JSON structure as each segment
9. Use English
10. Return JSON only, no additional text

"""


def _weekly_tool_schema() -> list[dict]:
    """返回 Anthropic tool use schema for submit_weekly_report。"""
    return [{
        "name": "submit_weekly_report",
        "description": "提交结构化周报",
        "input_schema": {
            "type": "object",
            "properties": {
                "week": {"type": "string"},
                "summary": {"type": "string"},
                "project_progress": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "project": {"type": "string"},
                        "days_active": {"type": "integer"},
                        "accomplishments": {"type": "array",
                                            "items": {"type": "string"}},
                        "blockers": {"type": "array",
                                     "items": {"type": "string"}},
                        "status": {"type": "string",
                                   "enum": ["active", "completed", "paused"]},
                    },
                    "required": ["project", "days_active", "status"],
                }},
                "key_tasks": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "date": {"type": "string"},
                        "status": {"type": "string",
                                   "enum": ["completed", "in_progress",
                                            "blocked"]},
                        "description": {"type": "string"},
                        "importance": {"type": "integer",
                                       "minimum": 1, "maximum": 10},
                    },
                    "required": ["title", "status", "importance"],
                }},
                "problems_resolved": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "problem": {"type": "string"},
                        "solution": {"type": "string"},
                        "date": {"type": "string"},
                        "project": {"type": "string"},
                    },
                    "required": ["problem", "solution"],
                }},
                "learnings": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "category": {"type": "string",
                                     "enum": ["architecture", "debugging",
                                              "tools", "domain"]},
                        "content": {"type": "string"},
                        "importance": {"type": "integer",
                                       "minimum": 1, "maximum": 10},
                    },
                    "required": ["category", "content", "importance"],
                }},
                "ai_usage_notes": {"type": "object", "properties": {
                    "effective_patterns": {"type": "array",
                                           "items": {"type": "string"}},
                    "limitations_encountered": {"type": "array",
                                                "items": {"type": "string"}},
                }},
                "next_week_outlook": {"type": "string"},
            },
            "required": ["week", "summary", "project_progress", "key_tasks"],
        },
    }]


def _build_weekly_config(prompt_text: str, timeout: int = TIMEOUT_WEEKLY) -> LLMCallConfig:
    """构建周报专用的 LLMCallConfig。"""
    return LLMCallConfig(
        prompt=prompt_text,
        timeout=timeout,
        anthropic_tools=_weekly_tool_schema(),
        anthropic_tool_name="submit_weekly_report",
        thinking=_LOW_THINKING,
    )


def _weekly_report_groups(daily_reports: list[dict]) -> list[list[dict]]:
    mid = len(daily_reports) // 2
    return [daily_reports[:mid], daily_reports[mid:]]


def _call_weekly_summarize_chunked(api: str, daily_reports: list[dict],
                                   week_label: str, timeout: int = TIMEOUT_WEEKLY,
                                   chunk_cache_dir: Optional[Path] = None
                                   ) -> dict:
    """分块调用 LLM 生成周报（当内容超过 chunk 上限时自动分组）。"""
    return call_period_summarize_chunked(
        api, daily_reports,
        summary_prompt=WEEKLY_SUMMARY_PROMPT,
        merge_prompt=WEEKLY_MERGE_PROMPT,
        build_config=lambda prompt_text: _build_weekly_config(prompt_text, timeout),
        timeout=timeout,
        format_reports=format_reports_for_llm,
        make_groups=_weekly_report_groups,
        target_line=f"Target week: {week_label}",
        chunk_cache_dir=chunk_cache_dir,
    )


# ─── 3. 图表生成 ────────────────────────────────────────────────────

def _generate_chart(usage_by_source: dict,
                    iso_year: int, iso_week: int) -> Optional[Path]:
    """生成周报 usage 图表（单 PNG 三子图，按来源）。"""
    monday, _ = _week_date_range(iso_year, iso_week)
    return generate_period_chart(usage_by_source, monday)


# ─── 4. 输出渲染 ────────────────────────────────────────────────────

def generate_weekly_markdown(report: dict, iso_year: int, iso_week: int,
                             chart_filename: Optional[str] = None) -> str:
    """将结构化周报渲染为 Markdown。"""
    week_label = _week_str(iso_year, iso_week)
    monday, sunday = _week_date_range(iso_year, iso_week)
    lines = []
    lines.append(f"# Weekly Report — {week_label} ({monday.isoformat()} ~ "
                 f"{sunday.isoformat()})\n")

    # 一段话总结
    if report.get("summary"):
        lines.append(f"> {report['summary']}\n")

    # ── 本周概览 ──
    stats = report.get("statistics", {})
    token_summary = report.get("token_usage_summary", {})
    codex_summary = report.get("codex_token_usage_summary", {})
    combined_summary = report.get("combined_token_usage_summary", {})
    if not _has_usage_data(combined_summary):
        combined_summary = combine_usage_summaries(token_summary, codex_summary)
    totals = combined_summary.get("totals", {})
    has_claude_usage = _has_usage_data(token_summary)
    has_codex_usage = _has_usage_data(codex_summary)

    lines.append("## Weekly Overview\n")
    lines.append("| Metric | Value |")
    lines.append("|------|------|")
    lines.append(f"| Date Range | {monday.isoformat()} ~ {sunday.isoformat()} |")
    lines.append(f"| Active Days | {stats.get('active_days', 0)} / 7 |")
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
            lines.append(f"| Claude Code Token | "
                         f"{claude_totals.get('totalTokens', 0):,} |")
            lines.append(f"| Claude Code Cost | "
                         f"${claude_totals.get('totalCost', 0):,.2f} |")
            lines.append(f"| Codex Token | "
                         f"{codex_totals.get('totalTokens', 0):,} |")
            lines.append(f"| Codex Cost | "
                         f"${codex_totals.get('totalCost', 0):,.2f} |")
        daily_avg_cost = combined_summary.get("daily_average_cost", 0)
        if daily_avg_cost:
            lines.append(f"| Daily Average Cost | ${daily_avg_cost:,.2f} |")
    lines.append("")

    # ── 项目进展 ──
    projects = report.get("project_progress", [])
    if projects:
        lines.append("## Project Progress\n")
        for p in projects:
            status_label = {
                "active": "🔄 active",
                "completed": "✅ completed",
                "paused": "⏸️ paused",
            }.get(p.get("status", ""), p.get("status", ""))
            lines.append(f"### {p.get('project', '(unknown)')} "
                         f"({p.get('days_active', '?')} days active) "
                         f"— {status_label}\n")
            accomplishments = p.get("accomplishments", [])
            if accomplishments:
                lines.append("**Accomplishments:**")
                for a in accomplishments:
                    lines.append(f"- {a}")
                lines.append("")
            blockers = p.get("blockers", [])
            if blockers:
                lines.append("**Blockers:**")
                for b in blockers:
                    lines.append(f"- ⚠️ {b}")
                lines.append("")

    # ── 关键任务 ──
    tasks = report.get("key_tasks", [])
    if tasks:
        lines.append("## Key Tasks\n")
        status_icons = {"completed": "✅", "in_progress": "🔄",
                        "blocked": "🚫"}
        for t in tasks:
            icon = status_icons.get(t.get("status", ""), "•")
            date_str = f" ({t['date']})" if t.get("date") else ""
            lines.append(f"- {icon} **{t.get('title', '(untitled)')}**{date_str} — "
                         f"{t.get('description', '')}")
        lines.append("")

    # ── 问题与解决方案 ──
    problems = report.get("problems_resolved", [])
    if problems:
        lines.append("## Problems & Solutions\n")
        for i, p in enumerate(problems, 1):
            proj_str = f" [{p['project']}]" if p.get("project") else ""
            date_str = f" ({p['date']})" if p.get("date") else ""
            lines.append(f"### {i}. {p.get('problem', '(unknown)')}{proj_str}{date_str}\n")
            lines.append(f"**Solution:** {p.get('solution', '—')}\n")

    # ── 学习收获 ──
    learnings = report.get("learnings", [])
    if learnings:
        lines.append("## Learnings\n")
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
                lines.append(f"- {item.get('content', '')}")
            lines.append("")

    # ── AI 使用备注 ──
    ai_notes = report.get("ai_usage_notes", {})
    if ai_notes and not isinstance(ai_notes, dict):
        # Off-schema LLM output (list/str) — render as plain bullets
        lines.append("## AI Usage Notes\n")
        for item in ai_notes if isinstance(ai_notes, list) else [ai_notes]:
            lines.append(f"- {item}")
        lines.append("")
    elif ai_notes:
        effective = ai_notes.get("effective_patterns", [])
        limitations = ai_notes.get("limitations_encountered", [])
        if effective or limitations:
            lines.append("## AI Usage Notes\n")
            if effective:
                lines.append("**Effective Patterns:**")
                for p in effective:
                    lines.append(f"- ✓ {p}")
                lines.append("")
            if limitations:
                lines.append("**Limitations:**")
                for l in limitations:
                    lines.append(f"- ✗ {l}")
                lines.append("")

    # ── 下周展望 ──
    outlook = report.get("next_week_outlook")
    if outlook:
        lines.append("## Next Week Outlook\n")
        lines.append(f"{outlook}\n")

    # ── Token 用量统计 ──
    if _has_usage_data(combined_summary):
        lines.append("## Token Usage Statistics\n")

        from .usage_card import render_usage_card
        by_source = (report.get("token_usage_by_source_summary")
                     or {"claude_code": token_summary, "codex": codex_summary})
        card = render_usage_card(by_source, f"AI Usage · {week_label}")
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


def generate_weekly_hugo_post(markdown_body: str, iso_year: int,
                              iso_week: int, hugo_site: Path,
                              chart_path: Optional[Path] = None,
                              api: str = DEFAULT_BACKEND,
                              force: bool = False,
                              overwrite_human: bool = False) -> Path:
    """将周报渲染为 Hugo bugJournal 格式并写入 staging content 目录（双语）。"""
    week_label = _week_str(iso_year, iso_week)
    _, sunday = _week_date_range(iso_year, iso_week)
    return generate_period_hugo_post(
        markdown_body, hugo_site,
        title=f"Weekly Summary {week_label}",
        post_date=sunday,
        hour=23, minute=59, second=0,
        keywords=["Bug Journal", "Weekly Summary"],
        fallback_summary=f"{week_label} Weekly AI conversation summary",
        content_parts=("bugJournal", "weekly"),
        filename=f"{week_label}-weekly.md",
        chart_path=chart_path,
        chart_image_subdir="weekly",
        api=api, force=force, overwrite_human=overwrite_human,
    )


def save_weekly_report(report: dict, markdown: str, iso_year: int,
                       iso_week: int, output_dir: Path) -> tuple[Path, Path]:
    """保存周报的 Markdown 和 JSON。"""
    week_label = _week_str(iso_year, iso_week)
    output_dir.mkdir(parents=True, exist_ok=True)

    md_path = output_dir / f"{week_label}-weekly.md"
    json_path = output_dir / f"{week_label}-weekly.json"

    from .backup import backup_existing
    backup_existing(md_path, json_path)

    _atomic_write(md_path, markdown)
    print(f"[ok] 周报 Markdown 已保存: {md_path}")

    _atomic_write(json_path, json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[ok] 周报 JSON 已保存: {json_path}")

    return md_path, json_path


# ─── 5. 缓存 ────────────────────────────────────────────────────────

def _cache_dir(reports_dir: Path) -> Path:
    return period_cache_dir("weekly")


def _load_weekly_cache(reports_dir: Path, iso_year: int, iso_week: int,
                       source_hash: str) -> Optional[dict]:
    """加载周报缓存。返回 None 表示未命中。"""
    return load_period_cache(
        _cache_dir(reports_dir), _week_str(iso_year, iso_week), source_hash)


def _save_weekly_cache(reports_dir: Path, iso_year: int, iso_week: int,
                       result: dict, source_hash: str) -> None:
    """保存周报缓存（附带源哈希用于失效检测）。"""
    save_period_cache(
        _cache_dir(reports_dir), _week_str(iso_year, iso_week),
        result, source_hash)


# ─── 6. CLI 命令 ────────────────────────────────────────────────────

def cmd_generate(args):
    """生成周报：load → cache check → LLM → aggregate → markdown → save → deploy。"""
    iso_year, iso_week = _parse_week(args.week)
    week_label = _week_str(iso_year, iso_week)
    monday, sunday = _week_date_range(iso_year, iso_week)
    print(f"[info] 目标周: {week_label} ({monday.isoformat()} ~ "
          f"{sunday.isoformat()})")

    api = resolve_period_api(args)
    reports_dir = resolve_reports_dir(args)

    # 检查已有输出
    force = getattr(args, "force", False)
    no_cache = getattr(args, "no_cache", False)
    existing_json = reports_dir / f"{week_label}-weekly.json"

    # 定型检查：过去的周（周日 < 今天）视为 finalized
    today = date.today()
    is_past_week = sunday < today

    if existing_json.exists() and not force and not no_cache:
        try:
            with open(existing_json, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
            if existing_data.get("_finalized") and is_past_week:
                print(f"[info] 周报已定型 (finalized): {existing_json}")
                print(f"[info] 使用 --force 强制重新生成")
                return
        except (OSError, json.JSONDecodeError):
            pass
        print(f"[info] 周报已存在: {existing_json}")
        print(f"[info] 使用 --force 重新生成，或 --no-cache 忽略 LLM 缓存")
        return

    # 加载日报
    daily_reports = load_weekly_reports(reports_dir, iso_year, iso_week)
    if not daily_reports:
        print(f"[warn] 未找到 {week_label} 的日报文件 "
              f"({monday.isoformat()} ~ {sunday.isoformat()}, "
              f"在 {reports_dir})")
        sys.exit(0)
    print(f"[info] 加载了 {len(daily_reports)} 份日报")

    timeout = getattr(args, "timeout", TIMEOUT_WEEKLY)
    llm_result = run_cached_period_llm(
        cache_dir=_cache_dir(reports_dir),
        label=week_label,
        daily_reports=daily_reports,
        no_cache=no_cache,
        force=force,
        call_llm_fn=lambda chunk_dir: _call_weekly_summarize_chunked(
            api, daily_reports, week_label, timeout=timeout,
            chunk_cache_dir=chunk_dir),
    )

    usage_by_source = collect_usage_by_source(daily_reports)
    token_usage = usage_by_source.get("claude_code", {})
    codex_token_usage = usage_by_source.get("codex", {})
    combined_token_usage = combine_usage_summaries(*usage_by_source.values())
    statistics = compute_weekly_statistics(daily_reports, iso_year, iso_week)

    # 组装最终报告
    report = {
        "week": week_label,
        "date_range": {
            "start": monday.isoformat(),
            "end": sunday.isoformat(),
        },
        **llm_result,
        "statistics": statistics,
        "token_usage_by_source_summary": usage_by_source,
        "token_usage_summary": token_usage,
        "codex_token_usage_summary": codex_token_usage,
        "combined_token_usage_summary": combined_token_usage,
    }

    # 标记定型状态
    if is_past_week:
        report["_finalized"] = True

    # 渲染 Markdown（usage 卡片内嵌，无需图表文件）
    markdown = generate_weekly_markdown(report, iso_year, iso_week)

    # 保存
    save_weekly_report(report, markdown, iso_year, iso_week, reports_dir)

    # Hugo 部署
    if getattr(args, "deploy", False):
        hugo_site = require_hugo_site(args)

        generate_weekly_hugo_post(markdown, iso_year, iso_week,
                                  hugo_site, api=args.api, force=force,
                                  overwrite_human=getattr(args, "overwrite_human", False))
        run_hugo_update(hugo_site)

    print(f"\n[ok] 周报生成完成: {week_label}")


def cmd_deploy(args):
    """从已保存的周报回放部署到 Hugo — 不重跑 LLM（对应 daily deploy 的语义）。

    已部署状态 = Hugo 内容目录中同名文件存在；--force 重新部署（覆盖前自动
    备份到 outputs/backups/website-force/）。"""
    reports_dir = resolve_reports_dir(args)
    hugo_site = require_hugo_site(args)

    if getattr(args, "week", None):
        iso_year, iso_week = _parse_week(args.week)
        md_files = [reports_dir / f"{_week_str(iso_year, iso_week)}-weekly.md"]
        md_files = [f for f in md_files if f.exists()]
        if not md_files:
            print(f"[warn] 未找到周报: {args.week}")
            sys.exit(0)
    else:
        md_files = sorted(reports_dir.glob("*-weekly.md"))
        if not md_files:
            print(f"[warn] {reports_dir} 中没有周报 .md 文件")
            sys.exit(0)

    staged_dir = resolve_site_content_dir(hugo_site, "bugJournal", "weekly")
    deployed = {p.stem for p in staged_dir.glob("*-weekly.md")}
    force = getattr(args, "force", False)
    to_deploy = [f for f in md_files if force or f.stem not in deployed]

    print(f"[info] 周报总数 {len(md_files)}, 已部署 {len(md_files) - len(to_deploy)}, "
          f"待部署 {len(to_deploy)}")
    if not to_deploy:
        print("[ok] 所有周报均已部署")
        return

    from common.paths import IMAGES_DIR
    for md_file in to_deploy:
        week_label = md_file.stem[:-len("-weekly")]
        iso_year, iso_week = _parse_week(week_label)
        monday, _ = _week_date_range(iso_year, iso_week)
        chart = IMAGES_DIR / "summarize" / f"{monday.isoformat()}-usage.png"
        generate_weekly_hugo_post(
            md_file.read_text(encoding="utf-8"), iso_year, iso_week, hugo_site,
            chart_path=chart if chart.exists() else None,
            force=force,
            overwrite_human=getattr(args, "overwrite_human", False))

    run_hugo_update(hugo_site)


def cmd_list(args):
    """列出所有可用周及其日报数量。"""
    reports_dir = resolve_reports_dir(args)

    if not reports_dir.exists():
        print(f"[warn] 报告目录不存在: {reports_dir}")
        return

    # 按 ISO 周分组
    weeks: dict[str, list[str]] = {}
    for f in sorted(reports_dir.glob("????-??-??.json")):
        if "monthly" in f.stem or "weekly" in f.stem:
            continue
        try:
            d = date.fromisoformat(f.stem)
        except ValueError:
            continue
        iso_year, iso_week, _ = d.isocalendar()
        week_key = _week_str(iso_year, iso_week)
        weeks.setdefault(week_key, []).append(f.stem)

    if not weeks:
        print("[info] 没有找到日报文件")
        return

    print(f"{'周':<12} {'日报数':>6}  {'日期范围':<30} {'已有周报':>8}")
    print("-" * 64)
    for week_key in sorted(weeks):
        dates = weeks[week_key]
        count = len(dates)
        # 解析周 label 获取日期范围
        parts = week_key.upper().split("-W")
        iso_year, iso_week = int(parts[0]), int(parts[1])
        monday, sunday = _week_date_range(iso_year, iso_week)
        date_range = f"{monday.isoformat()} ~ {sunday.isoformat()}"
        weekly_exists = (
            reports_dir / f"{week_key}-weekly.json").exists()
        marker = "  ✅" if weekly_exists else ""
        print(f"{week_key:<12} {count:>6}  {date_range:<30} {marker}")

    total_reports = sum(len(v) for v in weeks.values())
    print(f"\n共 {len(weeks)} 周, {total_reports} 份日报")


def main():
    parser = argparse.ArgumentParser(description="AI 对话周报总结工具")
    subparsers = parser.add_subparsers(dest="command")

    # ── generate 子命令 ──
    sp_gen = subparsers.add_parser("generate", help="生成周报")
    sp_gen.add_argument("--week", type=str, default=None,
                        help="目标周 (YYYY-WNN)，默认上一周")
    add_generate_arguments(sp_gen, timeout_default=resolved_timeout_weekly())
    sp_gen.set_defaults(**cli_defaults())

    sp_dep = subparsers.add_parser(
        "deploy", help="从已保存周报回放部署到 Hugo（不重跑 LLM）")
    sp_dep.add_argument("--week", type=str, default=None,
                        help="只部署指定周 (YYYY-WNN)，默认全部未部署周报")
    add_deploy_arguments(sp_dep)
    sp_dep.set_defaults(**cli_defaults())

    # ── list 子命令 ──
    sp_list = subparsers.add_parser("list", help="列出可用周及日报数量")
    sp_list.add_argument("--output", type=str, default=None,
                         help="报告目录 (默认 outputs/reports/summarize/)")

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
