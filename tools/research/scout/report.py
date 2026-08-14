"""Report generation, Hugo deployment, and literature notes for Research Scout."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from pathlib import Path

from common.bilingual import write_bilingual
from common.io import atomic_write
from common.hugo import run_hugo_update
from common.site_staging import resolve_site_content_dir, write_site_content

from research.scout.config import (
    PROJECTS_DIR,
    TOP_PAPERS_IN_REPORT,
    resolve_param,
    get_logger,
)
from research.scout.search import paper_id as _paper_id, paper_url as _paper_url

logger = get_logger()


def _truncate(text: str, max_len: int) -> str:
    """Truncate text to max_len, appending '...' if needed."""
    return text[:max_len - 3] + "..." if len(text) > max_len else text


def _cell(text: str) -> str:
    """Sanitize text for a Markdown table cell: escape pipes, collapse newlines."""
    return str(text).replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _field(lines: list[str], label: str, value: str) -> None:
    """Append a bold-labeled field line if value is non-empty."""
    if value:
        lines.append(f"- **{label}**: {value}")


# ─── Report generation ──────────────────────────────────────────────

def generate_daily_report(projects_data: dict[str, dict],
                          report_date: date) -> dict:
    """Assemble daily report JSON structure."""
    report = {
        "date": report_date.isoformat(),
        "generated_at": datetime.now().isoformat(),
        "projects": {},
    }

    for pid, data in projects_data.items():
        project = data["project"]
        high_papers = data.get("high_relevance", [])
        low_papers = data.get("low_relevance", [])
        stats = data.get("screening_stats", {})
        directions = data.get("directions", [])

        # Resolve per-project so it matches insight.py's resolution (project dict, not None).
        top_n = resolve_param(None, project, "top_papers_in_report", TOP_PAPERS_IN_REPORT)
        top_papers = high_papers[:top_n]
        papers_summary = []
        for p in top_papers:
            papers_summary.append({
                "paper_id": _paper_id(p),
                "source": p.get("source", "arxiv"),
                "arxiv_id": p.get("arxiv_id", ""),
                "title": p.get("title", ""),
                "authors": p.get("authors", [])[:5],
                "published": p.get("published", ""),
                "url": _paper_url(p),
                "venue": p.get("venue", ""),
                "paper_type": p.get("paper_type", ""),
                "relevance": p.get("relevance", 0),
                "novelty": p.get("novelty", 0),
                "inspiration": p.get("inspiration", 0),
                "composite_score": p.get("composite_score", 0),
                "two_sentence_summary": p.get("two_sentence_summary", ""),
                "suggestion": p.get("suggestion", ""),
                "highlights": p.get("highlights", []),
                "relevant_open_questions": p.get("relevant_open_questions", []),
                "citation_analysis": p.get("citation_analysis"),
                "insight_analysis": p.get("insight_analysis"),
                "review_analysis": p.get("review_analysis"),
            })

        low_summary = []
        for p in low_papers:
            low_summary.append({
                "paper_id": _paper_id(p),
                "source": p.get("source", "arxiv"),
                "arxiv_id": p.get("arxiv_id", ""),
                "title": p.get("title", ""),
                "url": _paper_url(p),
                "first_author": p.get("first_author", ""),
                "venue": p.get("venue", ""),
                "paper_type": p.get("paper_type", ""),
                "motivation": p.get("motivation", ""),
                "innovation_point": p.get("innovation_point", ""),
            })

        report["projects"][pid] = {
            "title": project["title"],
            "screening_stats": stats,
            "high_relevance_count": len(high_papers),
            "top_papers": papers_summary,
            "low_relevance_papers": low_summary,
            "directions": directions,
            "writing_guide": data.get("writing_guide", {}),
        }

    return report


def generate_report_markdown(report: dict) -> str:
    """Render daily report JSON to Markdown (English labels, all 3 stages)."""
    lines = []
    report_date = report.get("date", "unknown")
    lines.append(f"# Research Scout Daily Report — {report_date}\n")

    for pid, pdata in report.get("projects", {}).items():
        lines.append(f"## {pdata['title']} (`{pid}`)\n")

        stats = pdata.get("screening_stats", {})
        total = stats.get("total", 0)
        high_count = pdata.get("high_relevance_count", 0)
        lines.append(
            f"Found **{total}** papers, "
            f"screened **{high_count}** high-relevance papers.\n"
        )

        top_papers = pdata.get("top_papers", [])
        if top_papers:
            lines.append("### High-Relevance Papers\n")
            lines.append("| # | Score | Paper | Type | Summary |")
            lines.append("|---|-------|-------|------|---------|")
            for i, p in enumerate(top_papers, 1):
                score = p.get("composite_score", 0)
                title = _cell(_truncate(p.get("title", ""), 70))
                url = _paper_url(p)
                ptype = _cell(p.get("paper_type", ""))
                summary = _cell(_truncate(p.get("two_sentence_summary", ""), 100))
                lines.append(f"| {i} | {score:.1f} | [{title}]({url}) | {ptype} | {summary} |")
            lines.append("")

        if top_papers:
            lines.append("### Detailed Analysis\n")
            for p in top_papers:
                paper_id_val = _paper_id(p)
                title = p.get("title", "")
                url = _paper_url(p)
                lines.append(f"#### [{paper_id_val}] {title}\n")

                r = p.get("relevance", 0)
                n = p.get("novelty", 0)
                ins = p.get("inspiration", 0)
                cs = p.get("composite_score", 0)
                lines.append(f"- **Scores**: relevance={r}, novelty={n}, "
                             f"inspiration={ins}, composite={cs:.1f}")

                authors = p.get("authors", [])
                if authors:
                    lines.append(f"- **Authors**: {', '.join(authors[:5])}"
                                 + (" et al." if len(authors) > 5 else ""))

                _field(lines, "Venue", p.get("venue", ""))
                if p.get("source", "arxiv") != "arxiv":
                    _field(lines, "Source", p.get("source", ""))
                _field(lines, "Summary", p.get("two_sentence_summary", ""))
                _field(lines, "Suggestion", p.get("suggestion", ""))

                oq = p.get("relevant_open_questions", [])
                if oq:
                    lines.append(f"- **Relevant questions**: {', '.join(oq)}")

                highlights = p.get("highlights", [])
                if highlights and isinstance(highlights, list):
                    lines.append(f"- **Highlights**:")
                    for hi, h in enumerate(highlights, 1):
                        if not isinstance(h, dict):
                            continue
                        point = h.get("point", "")
                        why = h.get("why", "")
                        value = h.get("value_to_us", "")
                        direction = h.get("our_direction", "")
                        lines.append(f"  {hi}. **{point}**")
                        if why:
                            lines.append(f"     - Design motivation: {why}")
                        if value:
                            lines.append(f"     - Value to us: {value}")
                        if direction:
                            lines.append(f"     - Action suggestion: {direction}")

                ca = p.get("citation_analysis")
                if ca and isinstance(ca, dict):
                    fwd = ca.get("total_forward_citations", 0)
                    refs = ca.get("total_references", 0)
                    lines.append(f"\n##### Citation Impact Analysis\n")
                    lines.append(f"**Forward Citations**: {fwd} | **References**: {refs}\n")

                    top_citing = ca.get("top_citing_papers", [])
                    if top_citing:
                        lines.append(f"**Top Citing Papers** (top {min(len(top_citing), 5)}):\n")
                        lines.append("| # | Year | Citations | Title | Venue |")
                        lines.append("|---|------|------|------|------|")
                        for ci, tc in enumerate(top_citing[:5], 1):
                            t = _cell(_truncate(tc.get("title", ""), 60))
                            lines.append(
                                f"| {ci} | {tc.get('year', '')} | "
                                f"{tc.get('citation_count', 0)} | {t} | "
                                f"{_cell(tc.get('venue', ''))} |"
                            )
                        lines.append("")

                    ia = ca.get("influence_analysis", {})
                    if isinstance(ia, dict):
                        reason = ia.get("popularity_reason", "")
                        if reason:
                            lines.append(f"**Influence Analysis**: {reason}\n")
                        dirs = ia.get("followup_directions", [])
                        if dirs:
                            lines.append("**Follow-up Directions**:")
                            for d in dirs:
                                lines.append(f"- {d}")
                            lines.append("")
                        trend = ia.get("trend_impact", "")
                        if trend:
                            lines.append(f"**Trend Impact**: {trend}\n")

                lines.append(f"- **Link**: {url}\n")

        directions = pdata.get("directions", [])
        if directions:
            lines.append("### New Direction Suggestions\n")
            for i, d in enumerate(directions, 1):
                feasibility = d.get("feasibility", "medium")
                lines.append(f"**{i}. {d.get('title', '')}** (Feasibility: {feasibility})\n")
                lines.append(f"{d.get('description', '')}\n")
                related = d.get("related_papers", [])
                if related:
                    lines.append(f"- Related papers: {', '.join(related)}")
                questions = d.get("addresses_questions", [])
                if questions:
                    lines.append(f"- Addresses questions: {', '.join(questions)}")
                lines.append("")

        low_papers = pdata.get("low_relevance_papers", [])
        if low_papers:
            lines.append(f"### Literature Reading Log\n")
            lines.append(f"<details><summary>Low-relevance papers ({len(low_papers)})</summary>\n")
            lines.append("| # | Paper | Type | First Author | Venue | Motivation | Innovation |")
            lines.append("|---|-------|------|--------------|-------|------------|------------|")
            for i, p in enumerate(low_papers, 1):
                title = _cell(_truncate(p.get("title", ""), 60))
                url = _paper_url(p)
                ptype = _cell(p.get("paper_type", ""))
                first_author = _cell(p.get("first_author", ""))
                venue = _cell(p.get("venue", ""))
                motivation = _cell(_truncate(p.get("motivation", ""), 80))
                innovation = _cell(_truncate(p.get("innovation_point", ""), 80))
                lines.append(
                    f"| {i} | [{title}]({url}) | {ptype} | {first_author} | "
                    f"{venue} | {motivation} | {innovation} |"
                )
            lines.append("\n</details>\n")

        # ── Insight Analysis (Stage 4+5) ──
        insight_papers = [p for p in top_papers
                         if p.get("insight_analysis") or p.get("review_analysis")]
        if insight_papers:
            lines.append("### Paper Deep Insights (Insight Analysis)\n")
            for p in insight_papers:
                pid_val = _paper_id(p)
                title = p.get("title", "")
                lines.append(f"#### [{pid_val}] {title}\n")
                lines.append(render_insight_details(p))
                lines.append(render_review_summary(p))
                lines.append("")

        # ── Writing Guide ──
        writing_guide = pdata.get("writing_guide", {})
        if writing_guide:
            lines.append("### Research Writing Guide\n")
            lines.append(generate_writing_guide_section(writing_guide))
            lines.append("")

        lines.append("---\n")

    return "\n".join(lines)


def render_insight_details(paper: dict) -> str:
    """Render insight analysis for a single paper as Markdown."""
    lines = []
    ia = paper.get("insight_analysis", {})
    if not ia:
        return ""

    ws = ia.get("writing_structure", {})
    if ws:
        lines.append("**Writing Structure**:")
        narrative = ws.get("narrative_flow", "")
        if narrative:
            lines.append(f"- Narrative flow: {narrative}")
        pattern = ws.get("section_pattern", [])
        if pattern:
            if isinstance(pattern, list):
                lines.append(f"- Section pattern: {' → '.join(pattern)}")
            else:
                lines.append(f"- Section pattern: {pattern}")
        style = ws.get("argument_style", "")
        if style:
            lines.append(f"- Argument style: {style}")

    pub = ia.get("publishability", {})
    if pub:
        lines.append("\n**Publishability**:")
        strengths = pub.get("key_strengths", [])
        if strengths:
            if isinstance(strengths, list):
                for s in strengths:
                    lines.append(f"- Strength: {s}")
            else:
                lines.append(f"- Strength: {strengths}")
        pos = pub.get("positioning_strategy", "")
        if pos:
            lines.append(f"- Positioning strategy: {pos}")
        exp = pub.get("experiment_design", "")
        if exp:
            lines.append(f"- Experiment design: {exp}")

    ke = ia.get("knowledge_extraction", {})
    if ke:
        lines.append("\n**Core Knowledge**:")
        insights = ke.get("core_insights", [])
        if insights:
            if isinstance(insights, list):
                for ins in insights:
                    lines.append(f"- Insight: {ins}")
            else:
                lines.append(f"- Insight: {insights}")
        techniques = ke.get("reusable_techniques", [])
        if techniques:
            if isinstance(techniques, list):
                for t in techniques:
                    lines.append(f"- Reusable technique: {t}")
            else:
                lines.append(f"- Reusable technique: {techniques}")
        hints = ke.get("implementation_hints", [])
        if hints:
            if isinstance(hints, list):
                for h in hints:
                    lines.append(f"- Implementation hint: {h}")
            else:
                lines.append(f"- Implementation hint: {hints}")

    return "\n".join(lines)


def render_review_summary(paper: dict) -> str:
    """Render OpenReview review consensus for a single paper as Markdown."""
    ra = paper.get("review_analysis", {})
    if not ra:
        return ""

    lines = []
    review_count = ra.get("review_count", 0)
    mode = ra.get("mode", "")
    lines.append(f"\n**Review Opinions** ({review_count} reviewer{'s' if review_count > 1 else ''}"
                 f"{', limited' if mode == 'limited' else ''}):")

    avg = ra.get("average_rating", "")
    if avg:
        lines.append(f"- Average rating: {avg}")

    for field, label in [
        ("consensus_strengths", "Consensus Strengths"),
        ("consensus_weaknesses", "Consensus Weaknesses"),
        ("controversies", "Controversies"),
    ]:
        val = ra.get(field, [])
        if val:
            if isinstance(val, list):
                for item in val:
                    lines.append(f"- {label}: {item}")
            else:
                lines.append(f"- {label}: {val}")

    meta = ra.get("meta_review_summary", "")
    if meta:
        lines.append(f"- Meta-review: {meta}")

    takeaway = ra.get("key_takeaway", "")
    if takeaway:
        lines.append(f"- Key takeaway: {takeaway}")

    return "\n".join(lines)


def generate_writing_guide_section(writing_guide: dict) -> str:
    """Render cross-paper writing guide as Markdown."""
    lines = []

    sections = [
        ("writing_norms", "Domain Writing Norms"),
        ("review_focus", "Review Focus"),
        ("methodology_takeaways", "Methodology Takeaways"),
        ("code_references", "Code References"),
    ]

    for key, title in sections:
        content = writing_guide.get(key, "")
        if content:
            lines.append(f"**{title}**\n")
            lines.append(f"{content}\n")

    return "\n".join(lines)


def save_report(report: dict, markdown: str, reports_dir: Path,
                report_date: date) -> tuple[Path, Path]:
    """Save daily report JSON + Markdown."""
    reports_dir.mkdir(parents=True, exist_ok=True)
    date_str = report_date.isoformat()

    json_path = reports_dir / f"{date_str}-research.json"
    md_path = reports_dir / f"{date_str}-research.md"

    atomic_write(json_path, json.dumps(report, ensure_ascii=False, indent=2))
    atomic_write(md_path, markdown)

    logger.info("Report saved:")
    logger.info("  JSON: %s", json_path)
    logger.info("  Markdown: %s", md_path)
    return json_path, md_path


# ─── Hugo deployment ────────────────────────────────────────────────

def generate_hugo_post(markdown_body: str, report_date: date,
                       hugo_site: Path, api: str = "claude_cli",
                       force: bool = False,
                       overwrite_human: bool = False) -> Path:
    """Render research report as Hugo post with frontmatter (bilingual)."""
    summary = f"Research Scout Daily Report {report_date.isoformat()}"
    for line in markdown_body.splitlines():
        if line.startswith("## "):
            summary = f"Research Scout: {line[3:].strip()}"
            break
    summary = summary.replace('"', '\\"')

    frontmatter = f"""---
title: "Research Scout {report_date.isoformat()}"
date: {report_date.isoformat()}T22:00:00-05:00
keywords:
- Research
- Research Scout
- Paper Review
summary: "{summary}"
draft: false
---

"""
    resolve_site_content_dir(hugo_site, "research")
    rel = Path("research") / f"{report_date.isoformat()}-research.md"
    en_path, zh_path = write_bilingual(hugo_site, rel, frontmatter + markdown_body,
                                       force=force, overwrite_human=overwrite_human)

    logger.info("Hugo post generated: %s", en_path)
    if zh_path:
        logger.info("Hugo post (translated): %s", zh_path)
    return en_path


# ─── Literature notes ───────────────────────────────────────────────

def append_literature_note(project_id: str, top_papers: list[dict],
                           report_date: date) -> None:
    """Append top papers to project overview.md literature notes section."""
    overview_path = PROJECTS_DIR / project_id / "overview.md"
    if not overview_path.exists():
        return

    content = overview_path.read_text(encoding="utf-8")

    marker = "<!-- research_scout auto-append below -->"
    if marker not in content:
        return

    section_heading = f"### {report_date.isoformat()} Daily Report"
    # Idempotent: don't append a second section for the same date on re-run.
    if section_heading in content:
        logger.info("Literature note for %s already present in %s; skipping",
                    report_date.isoformat(), overview_path)
        return

    note_lines = [f"\n{section_heading}\n"]
    for p in top_papers[:3]:
        pid = _paper_id(p)
        title = p.get("title", "")
        score = p.get("composite_score", 0)
        summary = p.get("two_sentence_summary", "")
        url = _paper_url(p)
        note_lines.append(f"- **[{pid}] [{title}]({url})** (score: {score:.1f})")
        if summary:
            note_lines.append(f"  - {summary}")
        highlights = p.get("highlights", [])
        if highlights and isinstance(highlights, list) and len(highlights) > 0:
            h = highlights[0]
            if isinstance(h, dict):
                value = h.get("value_to_us", "")
                if value:
                    note_lines.append(f"  - Value to us: {value}")

    append_text = "\n".join(note_lines) + "\n"

    # Insert directly below the marker line (newest section first), not at EOF,
    # so any content following the marker is preserved.
    head, sep, tail = content.partition(marker)
    new_content = head + sep + "\n" + append_text + tail
    atomic_write(overview_path, new_content)
    logger.info("Literature note appended to %s", overview_path)
