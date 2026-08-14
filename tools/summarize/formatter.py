"""Report generation: Markdown rendering, Hugo post creation, and file saving."""

import json
from datetime import date
from pathlib import Path
from typing import Optional

from common.io import atomic_write as _atomic_write
from common.llm import DEFAULT_BACKEND
from common.paths import REPORTS_DIR

from .period_report import generate_period_hugo_post

_DEFAULT_REPORTS_DIR = REPORTS_DIR / "summarize"


def _importance_sort_key(item):
    """排序键：level="high" → 0, "low" → 1, 无 → 2；同 level 内按 importance 降序。"""
    if isinstance(item, str):
        return (2, 0)  # 旧格式字符串排到末尾
    level = item.get("level", "")
    raw_importance = item.get("importance", 0)
    try:
        importance = int(raw_importance)
    except (TypeError, ValueError):
        importance = 0
    level_order = 0 if level == "high" else (1 if level == "low" else 2)
    return (level_order, -importance)


# ponytail: qwen (via ollama) sometimes emits these list fields as bare strings
# instead of the expected dicts, which crashes the .get()-based renderers and the
# project grouping. Wrap a bare string under the field's natural key; drop other
# junk (numbers/None/empty). Ceiling: if a field needs a different natural key,
# add it here. This is the trust boundary between LLM output and rendering.
_LIST_FIELD_KEY = {
    "tasks": "name",
    "problems_and_solutions": "problem",
    "human_vs_ai": "topic",
    "ai_limitations": "content",
    "learnings": "content",
    "conversation_summaries": "summary",
}


def _coerce_report_lists(report: dict) -> dict:
    """Normalize LLM list fields so every item is a dict (wrap bare strings)."""
    for field, key in _LIST_FIELD_KEY.items():
        raw = report.get(field)
        if isinstance(raw, list):
            report[field] = [it if isinstance(it, dict) else {key: it}
                             for it in raw
                             if isinstance(it, dict) or (isinstance(it, str) and it.strip())]
    return report


def _sort_report_by_importance(report: dict) -> dict:
    """按 level/importance 对报告各章节排序，兼容旧格式。"""
    _coerce_report_lists(report)
    for key in ("tasks", "problems_and_solutions", "human_vs_ai",
                "ai_limitations", "learnings"):
        items = report.get(key, [])
        if items:
            report[key] = sorted(items, key=_importance_sort_key)

    # conversation_summaries: 保持项目分组顺序，组内排序
    conv_summaries = report.get("conversation_summaries", [])
    if conv_summaries:
        grouped = {}
        for cs in conv_summaries:
            proj = cs.get("project", "Unknown Project")
            grouped.setdefault(proj, []).append(cs)
        sorted_summaries = []
        for proj, items in grouped.items():
            sorted_summaries.extend(sorted(items, key=_importance_sort_key))
        report["conversation_summaries"] = sorted_summaries

    return report


def _has_level_metadata(items: list) -> bool:
    """检测列表中是否有 level 字段。"""
    for item in items:
        if isinstance(item, dict) and item.get("level") in ("high", "low"):
            return True
    return False


def _split_by_level(items: list) -> tuple[list, list]:
    """分为 (high_items, low_items)。无 level 的归入 low。"""
    high, low = [], []
    for item in items:
        if isinstance(item, dict) and item.get("level") == "high":
            high.append(item)
        else:
            low.append(item)
    return high, low


def _render_content_list(lines: list[str], items: list, section_title: str,
                         high_title: str, low_title: str,
                         content_key: str = "content") -> None:
    """Render a list section with optional high/low level splitting."""
    if not items:
        return
    lines.append(f"## {section_title}\n")
    if isinstance(items[0], str):
        for item in items:
            lines.append(f"- {item}")
        lines.append("")
    elif _has_level_metadata(items):
        high, low = _split_by_level(items)
        for subset, title in [(high, high_title), (low, low_title)]:
            if subset:
                lines.append(f"### {title}\n")
                for item in subset:
                    lines.append(f"- {item.get(content_key, '')}")
                lines.append("")
    else:
        for item in items:
            content = item.get(content_key, item) if isinstance(item, dict) else item
            lines.append(f"- {content}")
        lines.append("")


def generate_markdown(report: dict, target_date: date,
                      chart_filename: Optional[str] = None) -> str:
    """将结构化报告渲染为 Markdown 日报。"""
    _coerce_report_lists(report)   # tolerate LLM emitting list items as bare strings
    _chart = chart_filename
    lines = []
    lines.append(f"# Daily Report — {target_date.isoformat()}\n")

    # 今日概览
    overview = report.get("daily_overview")
    if overview and isinstance(overview, dict):
        _OV_FIELDS = [("what", "What was done"), ("how", "How it was done"), ("impact", "Impact")]
        # 先收集渲染行，仅在确有内容时才加标题，避免出现孤立的空标题、丢失内容。
        ov_lines: list[str] = []
        if "global" in overview or "devices" in overview:
            # 多设备新格式（global / devices 可能只出现其一）
            g = overview.get("global") or {}
            if isinstance(g, str):
                # ponytail: LLM sometimes emits the overview as prose, not {what,how,impact}
                ov_lines.append(f"- {g}")
            else:
                for key, label in _OV_FIELDS:
                    if g.get(key):
                        ov_lines.append(f"- **{label}:** {g[key]}")
            if ov_lines:
                ov_lines.append("")
            for dev_name, dev_ov in (overview.get("devices") or {}).items():
                if isinstance(dev_ov, dict):
                    dev_lines = [f"- **{label}:** {dev_ov[key]}" for key, label in _OV_FIELDS if dev_ov.get(key)]
                elif isinstance(dev_ov, str) and dev_ov:
                    dev_lines = [f"- {dev_ov}"]
                else:
                    dev_lines = []
                if dev_lines:
                    ov_lines.append(f"### {dev_name}\n")
                    ov_lines.extend(dev_lines)
                    ov_lines.append("")
        else:
            # 扁平格式（单设备/旧格式）— 渲染任一存在的字段
            for key, label in _OV_FIELDS:
                if overview.get(key):
                    ov_lines.append(f"- **{label}:** {overview[key]}")
            if ov_lines:
                ov_lines.append("")
        if ov_lines:
            lines.append("## Daily Overview\n")
            lines.extend(ov_lines)

    # 一句话总结
    if report.get("summary"):
        lines.append(f"> {report['summary']}\n")

    # 任务列表
    tasks = report.get("tasks", [])
    if tasks:
        lines.append("## Tasks\n")
        status_icons = {"completed": "✅", "in_progress": "🔄", "blocked": "❌"}

        def _render_task(t):
            icon = status_icons.get(t.get("status", ""), "•")
            lines.append(f"- {icon} **{t.get('name', 'N/A')}** — {t.get('description', '')}")

        if _has_level_metadata(tasks):
            high, low = _split_by_level(tasks)
            if high:
                lines.append("### Architecture & Strategy\n")
                for t in high:
                    _render_task(t)
                lines.append("")
            if low:
                lines.append("### Implementation & Fixes\n")
                for t in low:
                    _render_task(t)
                lines.append("")
        else:
            for t in tasks:
                _render_task(t)
            lines.append("")

    # 问题与解决方案
    ps = report.get("problems_and_solutions", [])
    if ps:
        lines.append("## Problems & Solutions\n")

        has_levels = _has_level_metadata(ps)
        h_prefix = "####" if has_levels else "###"

        def _render_ps(items, start_idx=1):
            for i, item in enumerate(items, start_idx):
                lines.append(f"{h_prefix} {i}. {item.get('problem', 'N/A')}\n")
                lines.append(f"**Solution:** {item.get('solution', 'N/A')}\n")
                if item.get("key_insight"):
                    lines.append(f"**Key Insight:** {item['key_insight']}\n")

        if has_levels:
            high, low = _split_by_level(ps)
            idx = 1
            if high:
                lines.append("### Critical Issues\n")
                _render_ps(high, idx)
                idx += len(high)
            if low:
                lines.append("### General Issues\n")
                _render_ps(low, idx)
        else:
            _render_ps(ps)

    # 人类 vs AI
    hva = report.get("human_vs_ai", [])
    if hva:
        lines.append("## Human vs AI Approaches\n")

        has_levels = _has_level_metadata(hva)
        h_prefix = "####" if has_levels else "###"

        def _render_hva(item):
            lines.append(f"{h_prefix} {item.get('topic', 'N/A')}\n")
            lines.append(f"| Role | Approach |")
            lines.append(f"|------|------|")
            lines.append(f"| Human | {item.get('human_approach', 'N/A')} |")
            lines.append(f"| AI   | {item.get('ai_approach', 'N/A')} |")
            lines.append(f"\n**Difference Analysis:** {item.get('difference', 'N/A')}\n")

        if has_levels:
            high, low = _split_by_level(hva)
            if high:
                lines.append("### Strategic Level\n")
                for item in high:
                    _render_hva(item)
            if low:
                lines.append("### Implementation Level\n")
                for item in low:
                    _render_hva(item)
        else:
            for item in hva:
                _render_hva(item)

    # AI 局限性
    _render_content_list(lines, report.get("ai_limitations", []),
                         "AI Limitations", "Critical Limitations", "General Limitations")

    # 今日收获
    _render_content_list(lines, report.get("learnings", []),
                         "Learnings", "Key Learnings", "Practical Learnings")

    # 会话摘要
    conv_summaries = report.get("conversation_summaries", [])
    if conv_summaries:
        lines.append("## Conversation Summaries\n")
        outcome_icons = {
            "completed": "✅",
            "partial": "🔄",
            "exploratory": "🔍",
            "abandoned": "❌",
        }
        # 按 project 分组（保持顺序）
        grouped = {}
        for cs in conv_summaries:
            proj = cs.get("project", "Unknown Project")
            grouped.setdefault(proj, []).append(cs)

        multi_project = len(grouped) > 1
        for proj, items in grouped.items():
            if multi_project:
                lines.append(f"### {proj}\n")
            for cs in items:
                icon = outcome_icons.get(cs.get("outcome", ""), "•")
                topic = cs.get("topic", "")
                lines.append(f"**{icon} {topic}**")
                # 元信息行
                meta_parts = []
                if cs.get("timestamp"):
                    # 尝试提取时间部分
                    ts = cs["timestamp"]
                    if "T" in ts:
                        ts = ts.split("T")[1].split("+")[0].split("Z")[0]
                    meta_parts.append(ts)
                if cs.get("source"):
                    meta_parts.append(cs["source"])
                if meta_parts:
                    lines.append(f"_{' | '.join(meta_parts)}_")
                summary_text = cs.get("summary", "")
                if summary_text:
                    lines.append(f"{summary_text}")
                lines.append("")

    # Token 用量（chart-based rendering）
    by_source = report.get("token_usage_by_source")
    if not by_source:
        # backward compat: synthesize from legacy aliases
        by_source = {}
        if report.get("token_usage"):
            by_source["claude_code"] = report["token_usage"]
        if report.get("codex_token_usage"):
            by_source["codex"] = report["codex_token_usage"]

    if by_source:
        from .usage_card import render_usage_card
        card = render_usage_card(
            by_source, f"AI Usage · {target_date.isoformat()}")
        if card:
            lines.append("## Token Usage\n")
            lines.append(card + "\n")

    # 如果有解析错误，展示原始响应
    if report.get("parse_error"):
        lines.append("## ⚠️ Raw Response (JSON Parse Failed)\n")
        lines.append(f"```\n{report.get('raw_response', '')}\n```\n")

    return "\n".join(lines)


def generate_hugo_post(markdown_body: str, target_date: date, hugo_site: Path,
                       api: str = DEFAULT_BACKEND, pbar=None,
                       chart_path: Optional[Path] = None,
                       engine=None, force: bool = False,
                       overwrite_human: bool = False) -> Path:
    """将日报渲染为 Hugo bugJournal 格式并写入站点 content 目录（双语）。"""
    return generate_period_hugo_post(
        markdown_body, hugo_site,
        title=f"Bug Journal {target_date.isoformat()}",
        post_date=target_date,
        hour=0, minute=0, second=0,
        keywords=["Bug Journal"],
        fallback_summary="Daily AI conversation summary",
        content_parts=("bugJournal", "daily"),
        filename=f"{target_date.isoformat()}.md",
        chart_path=chart_path,
        chart_image_subdir="daily",
        api=api, force=force, overwrite_human=overwrite_human,
        engine=engine, pbar=pbar,
    )


def save_report(report: dict, markdown: str, target_date: date, output_dir: Path):
    """保存 Markdown 和 JSON 报告。"""
    output_dir.mkdir(parents=True, exist_ok=True)

    md_path = output_dir / f"{target_date.isoformat()}.md"
    json_path = output_dir / f"{target_date.isoformat()}.json"

    from .backup import backup_existing
    backup_existing(md_path, json_path)

    _atomic_write(md_path, markdown)
    print(f"[ok] Markdown 日报已保存: {md_path}")

    _atomic_write(json_path, json.dumps(report, ensure_ascii=False, indent=2))
    print(f"[ok] JSON 数据已保存: {json_path}")
