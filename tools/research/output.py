"""JSON and Markdown report rendering."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from common.io import atomic_write
from common.site_staging import resolve_site_content_dir, write_site_content
from research.models import ResearcherProfile


def _safe_filename(name: str) -> str:
    """Convert a researcher name to a collision-resistant safe filename.

    The cleaned slug strips punctuation and case, so distinct names like
    'A. Smith' and 'A Smith' would collapse to the same file and silently
    overwrite each other. Append a short hash of the original name so distinct
    names map to distinct files while identical names stay stable (every caller
    derives the same stem from the same name).
    """
    slug = re.sub(r'[^\w\s-]', '', name).strip().replace(' ', '_').lower()
    digest = hashlib.sha1(name.encode('utf-8')).hexdigest()[:6]
    return f"{slug}-{digest}" if slug else digest


def _yaml_str(value: Any) -> str:
    """Render a value as a safely double-quoted YAML scalar.

    Escapes backslashes first, then double quotes, so interpolation into
    frontmatter never produces malformed YAML for titles/summaries/themes
    containing quotes, backslashes, or newlines.
    """
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    # Collapse newlines/carriage returns which would break a single-line scalar.
    text = text.replace("\r", " ").replace("\n", " ")
    return f'"{text}"'


def _load_profile(path: Path) -> ResearcherProfile | None:
    """Load a researcher profile from JSON, returning None on error."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return ResearcherProfile.from_dict(data)
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as e:
        print(f"  [warn] Failed to load {path.name}: {e}")
        return None


def save_profile(profile: ResearcherProfile, profiles_dir: Path) -> Path:
    """Save researcher profile as JSON."""
    profiles_dir.mkdir(parents=True, exist_ok=True)

    filename = _safe_filename(profile.name) + ".json"
    path = profiles_dir / filename

    atomic_write(path, json.dumps(profile.to_dict(), ensure_ascii=False, indent=2))

    print(f"  Saved JSON: {path}")
    return path


def _render_report_lines(profile: ResearcherProfile) -> list[str]:
    """Build Markdown report lines for a researcher (shared by render_report and deploy_to_hugo)."""
    lines = []
    lines.append(f"# {profile.name} — Researcher Analysis Report")
    lines.append("")
    lines.append(f"**Analysis Mode**: {profile.mode} | "
                 f"**Analysis Time**: {profile.fetched_at[:19]}")
    lines.append("")

    # Tier badge
    lines.append(f"## Rating: {profile.tier.label_en} ({profile.tier_score:.1f}/100)")
    lines.append("")

    # Metrics table
    m = profile.metrics
    lines.append("## Basic Metrics")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|------|------|")
    lines.append(f"| Affiliation | {m.current_affiliation or 'Unknown'} |")
    lines.append(f"| h-index | {m.h_index} |")
    lines.append(f"| Total Citations | {m.total_citations:,} |")
    lines.append(f"| Recent Citations (5yr) | {m.recent_citations_5yr:,} |")
    lines.append(f"| Paper Count | {m.paper_count} |")
    lines.append(f"| Top Venue Papers | {m.top_venue_count} |")
    lines.append(f"| Publication Period | {m.first_paper_year} - {m.latest_paper_year} |")
    if profile.s2_author_id:
        s2_url = f"https://www.semanticscholar.org/author/{profile.s2_author_id}"
        lines.append(f"| Semantic Scholar | [{profile.s2_author_id}]({s2_url}) |")
    lines.append("")

    # Analysis sections
    analysis = profile.analysis
    if analysis:
        # Trajectory summary
        summary = analysis.get("trajectory_summary", "")
        if summary:
            lines.append("## Research Trajectory")
            lines.append("")
            lines.append(summary)
            lines.append("")

        # Breakthroughs
        breakthroughs = analysis.get("breakthroughs", [])
        if breakthroughs:
            lines.append("## Breakthrough Works")
            lines.append("")
            for i, bt in enumerate(breakthroughs, 1):
                title = bt.get("title", "")
                year = bt.get("year", "")
                desc = bt.get("description", "")
                why = bt.get("why_not_before", "")
                impact = bt.get("impact", "")
                tech = bt.get("technical_insight", "")

                lines.append(f"### {i}. {title} ({year})")
                lines.append("")
                if desc:
                    lines.append(f"**Description**: {desc}")
                    lines.append("")
                if why:
                    lines.append(f"**Why not before**: {why}")
                    lines.append("")
                if impact:
                    lines.append(f"**Impact**: {impact}")
                    lines.append("")
                if tech:
                    lines.append(f"**Technical Insight**: {tech}")
                    lines.append("")

        # Research themes
        themes = analysis.get("research_themes", [])
        if themes:
            lines.append("## Research Themes")
            lines.append("")
            for t in themes:
                lines.append(f"- {t}")
            lines.append("")

        # Methodology evolution
        method = analysis.get("methodology_evolution", "")
        if method:
            lines.append("## Methodology Evolution")
            lines.append("")
            lines.append(method)
            lines.append("")

        # Field impact
        impact = analysis.get("field_impact", "")
        if impact:
            lines.append("## Field Impact")
            lines.append("")
            lines.append(impact)
            lines.append("")

    # Students
    if profile.inferred_students:
        lines.append("## Inferred Students/Mentees")
        lines.append("")
        # Check if any student has source/status data (homepage-based discovery)
        has_source = any(s.source for s in profile.inferred_students)
        if has_source:
            lines.append("| Name | Source | Status | Co-authored | Score | Research Direction |")
            lines.append("|------|------|------|--------|----------|----------|")
            source_labels = {"homepage": "Homepage", "coauthorship": "Co-authorship", "both": "Both"}
            status_labels = {"current": "Current", "graduated": "Graduated", "postdoc": "Postdoc", "unknown": "-"}
            for s in profile.inferred_students:
                src = source_labels.get(s.source, s.source or "-")
                st = status_labels.get(s.status, s.status or "-")
                coauth = str(s.coauthor_count) if s.coauthor_count else "-"
                score = f"{s.relationship_score:.2f}" if s.relationship_score else "-"
                lines.append(
                    f"| {s.name} | {src} | {st} | {coauth} | "
                    f"{score} | {s.research_direction or '-'} |"
                )
        else:
            lines.append("| Name | Co-authored | First Author | Period | Score | Research Direction |")
            lines.append("|------|--------|--------|--------|----------|----------|")
            for s in profile.inferred_students:
                lines.append(
                    f"| {s.name} | {s.coauthor_count} | {s.first_author_count} | "
                    f"{s.collab_start_year}-{s.collab_end_year} | "
                    f"{s.relationship_score:.2f} | {s.research_direction or '-'} |"
                )
        lines.append("")

    # Top papers
    if profile.papers:
        lines.append("## Top Cited Papers (Top 20)")
        lines.append("")
        top = sorted(profile.papers, key=lambda p: p.citation_count, reverse=True)[:20]
        lines.append("| # | Year | Citations | Title |")
        lines.append("|---|------|------|------|")
        for i, p in enumerate(top, 1):
            year = p.published[:4] if p.published else "-"
            lines.append(f"| {i} | {year} | {p.citation_count:,} | {p.title} |")
        lines.append("")

    return lines


def render_report(profile: ResearcherProfile, reports_dir: Path) -> Path:
    """Render a Markdown report for a researcher."""
    reports_dir.mkdir(parents=True, exist_ok=True)

    filename = _safe_filename(profile.name) + ".md"
    path = reports_dir / filename

    lines = _render_report_lines(profile)
    content = "\n".join(lines)
    atomic_write(path, content)

    print(f"  Saved report: {path}")
    return path


def deploy_to_hugo(profile: ResearcherProfile, hugo_site: Path) -> Path | None:
    """Deploy a researcher profile report to staged Hugo content/research/."""
    filename = _safe_filename(profile.name) + ".md"
    resolve_site_content_dir(hugo_site, "research")

    # Build the markdown body (reuse render logic)
    lines = _render_report_lines(profile)
    markdown_body = "\n".join(lines)

    # Extract summary
    summary = f"{profile.name} — Researcher Analysis Report"
    trajectory = (profile.analysis or {}).get("trajectory_summary", "")
    if trajectory:
        first_line = trajectory.strip().split("\n")[0][:120]
        summary = f"{profile.name}: {first_line}"

    # Build frontmatter (all scalars/list items escaped via _yaml_str)
    date_str = profile.fetched_at[:10] if profile.fetched_at else "2026-01-01"
    themes = (profile.analysis or {}).get("research_themes", [])
    keywords = ["Research", "Researcher Profile"] + themes[:3]
    kw_lines = "\n".join(f"- {_yaml_str(k)}" for k in keywords)
    title = f"{profile.name} — Researcher Analysis Report"

    frontmatter = f"""---
title: {_yaml_str(title)}
date: {date_str}T22:00:00-05:00
keywords:
{kw_lines}
summary: {_yaml_str(summary)}
draft: false
---

"""
    post_path = write_site_content(
        hugo_site,
        Path("research") / filename,
        frontmatter + markdown_body,
    )

    print(f"  Hugo post generated: {post_path}")
    return post_path


def show_profile(name: str, profiles_dir: Path, reports_dir: Path | None = None) -> bool:
    """Display a cached researcher profile."""
    filename = _safe_filename(name) + ".json"
    path = profiles_dir / filename

    if not path.exists():
        print(f"No analysis data found for {name}. Please run: python -m research analyze \"{name}\"")
        return False

    profile = _load_profile(path)
    if profile is None:
        return False

    print(f"\n{'='*60}")
    print(f"  {profile.name} — {profile.tier.label_en} ({profile.tier_score:.1f}/100)")
    print(f"{'='*60}")

    m = profile.metrics
    print(f"  Affiliation: {m.current_affiliation or 'Unknown'}")
    print(f"  h-index: {m.h_index} | Citations: {m.total_citations:,} | "
          f"Recent 5yr: {m.recent_citations_5yr:,}")
    print(f"  Papers: {m.paper_count} | Top venues: {m.top_venue_count} | "
          f"Period: {m.first_paper_year}-{m.latest_paper_year}")
    print()

    analysis = profile.analysis
    if analysis:
        summary = analysis.get("trajectory_summary", "")
        if summary:
            print("  Research trajectory:")
            for line in summary.split("\n"):
                print(f"    {line}")
            print()

        themes = analysis.get("research_themes", [])
        if themes:
            print(f"  Research themes: {', '.join(themes)}")
            print()

    if profile.inferred_students:
        print(f"  Inferred students ({len(profile.inferred_students)}):")
        for s in profile.inferred_students:
            print(f"    - {s.name} (Score: {s.relationship_score:.2f}, "
                  f"Co-authored: {s.coauthor_count})")
        print()

    _rep_dir = reports_dir if reports_dir else profiles_dir.parent / "reports"
    report_path = _rep_dir / (_safe_filename(name) + ".md")
    if report_path.exists():
        print(f"  Full report: {report_path}")

    return True


def list_profiles(profiles_dir: Path) -> None:
    """List all analyzed researchers."""
    if not profiles_dir.exists():
        print("No researchers analyzed yet.")
        return

    profiles = sorted(profiles_dir.glob("*.json"))
    if not profiles:
        print("No researchers analyzed yet.")
        return

    print(f"\nAnalyzed researchers ({len(profiles)}):")
    print(f"{'':2s}{'Rating':8s} {'Score':6s} {'Name':25s} {'Mode':6s} {'Analyzed At'}")
    print(f"  {'-'*70}")

    for p_path in profiles:
        profile = _load_profile(p_path)
        if profile is None:
            continue
        time_str = profile.fetched_at[:16] if profile.fetched_at else "-"
        print(f"  {profile.tier.label_en:6s} {profile.tier_score:5.1f}  "
              f"{profile.name:25s} {profile.mode:6s} {time_str}")

    print()
