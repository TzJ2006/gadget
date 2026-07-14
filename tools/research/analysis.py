"""Main orchestrator: fetch data → LLM analysis → recursive exploration."""

from __future__ import annotations

import logging
from collections import defaultdict, deque
from datetime import datetime
from typing import Any

from research.apis.arxiv_client import search_papers_by_author, download_fulltext
from research.apis.semantic_scholar import (
    search_author,
    get_author_by_id,
    resolve_author_by_paper,
    get_author_papers,
    build_metrics,
    get_coauthor_data,
)
from research.cache import DiskCache
from research.llm import call_llm, parse_json_response
from research.models import (
    Paper,
    ResearcherProfile,
    ResearcherTier,
    StudentCandidate,
)
from research.output import save_profile, render_report
from research.prompts import (
    TRAJECTORY_ANALYSIS_PROMPT,
    TRAJECTORY_ANALYSIS_DETAILED_PROMPT,
    AWARD_IDENTIFICATION_PROMPT,
    STUDENT_EVALUATION_PROMPT,
    format_papers_for_prompt,
    format_full_texts,
    format_candidates_for_prompt,
)
from research.scoring import compute_tier_score, classify_tier
from research.student_discovery import score_student_candidates

logger = logging.getLogger(__name__)

# Award sort weight: higher = more prestigious
_AWARD_WEIGHT = {
    "best_paper": 4,
    "highlight": 3,
    "spotlight": 2,
    "oral": 1,
}

# Detailed-mode full-text budget: cap how much full text we embed in the
# trajectory prompt so a prolific researcher doesn't blow up the model context.
_FULLTEXT_MAX_PAPERS = 15
_FULLTEXT_MAX_CHARS = 120_000


def _budget_full_text_papers(
    papers_with_text: list[Paper],
    max_papers: int = _FULLTEXT_MAX_PAPERS,
    max_chars: int = _FULLTEXT_MAX_CHARS,
) -> list[Paper]:
    """Cap full-text papers by count and cumulative chars for the detailed prompt.

    Prefers the most-cited papers, then accumulates full text until the global
    character budget is exhausted. Returns the kept subset (input is unmodified).
    """
    ranked = sorted(papers_with_text, key=lambda p: p.citation_count, reverse=True)
    kept: list[Paper] = []
    total_chars = 0
    for p in ranked[:max_papers]:
        text_len = len(p.full_text or "")
        if kept and total_chars + text_len > max_chars:
            break
        kept.append(p)
        total_chars += text_len
    return kept


def _select_papers_by_year(
    arxiv_papers: list[Paper],
    s2_papers: list[dict],
    max_per_year: int = 10,
) -> list[Paper]:
    """Select papers by year: S2 as primary source, ArXiv enriches metadata.

    Returns papers sorted chronologically (earliest year first),
    with up to max_per_year papers per year, sorted by award weight then citations.
    """
    # Build ArXiv lookup by normalized title
    arxiv_by_title: dict[str, Paper] = {}
    for p in arxiv_papers:
        title_lower = p.title.lower().strip()
        if title_lower:
            arxiv_by_title[title_lower] = p

    # Convert S2 papers to Paper objects (primary data source)
    seen_titles: set[str] = set()
    all_papers: list[Paper] = []

    for s2p in s2_papers:
        title = s2p.get("title") or ""
        title_lower = title.lower().strip()
        if not title_lower or title_lower in seen_titles:
            continue
        seen_titles.add(title_lower)

        year = s2p.get("year") or 0
        published = f"{year}-01-01" if year else ""

        paper = Paper(
            title=title,
            citation_count=s2p.get("citationCount") or 0,
            venue=s2p.get("venue") or "",
            published=published,
            abstract=s2p.get("abstract") or "",
            authors=[a.get("name", "") for a in (s2p.get("authors") or [])],
        )

        # Enrich from ArXiv match (arxiv_id, pdf_url, categories, better abstract)
        arxiv_match = arxiv_by_title.get(title_lower)
        if arxiv_match:
            paper.arxiv_id = arxiv_match.arxiv_id
            paper.pdf_url = arxiv_match.pdf_url
            paper.categories = arxiv_match.categories
            if arxiv_match.abstract and len(arxiv_match.abstract) > len(paper.abstract):
                paper.abstract = arxiv_match.abstract
            if arxiv_match.published and not paper.published:
                paper.published = arxiv_match.published

        all_papers.append(paper)

    # Add ArXiv-only papers (new preprints not yet in S2)
    for arxiv_p in arxiv_papers:
        title_lower = arxiv_p.title.lower().strip()
        if title_lower and title_lower not in seen_titles:
            seen_titles.add(title_lower)
            all_papers.append(arxiv_p)

    # Group by year
    by_year: dict[int, list[Paper]] = defaultdict(list)
    for p in all_papers:
        year = int(p.published[:4]) if p.published and p.published[:4].isdigit() else 0
        by_year[year].append(p)

    # Sort within each year: award weight desc, then citation count desc.
    # NOTE: awards are identified AFTER this selection runs (see analyze_researcher:
    # _identify_awards is called on the selected papers), so at this point every
    # paper's award is still empty and the award-weight term is effectively dead —
    # the per-year cut here is driven purely by citation_count. This is intentional:
    # the cheaper way to keep the award signal would require running award
    # identification on ALL papers before selection (more LLM tokens). Instead,
    # _resort_after_awards() re-sorts the selected set once awards are known, which
    # fixes ordering within the kept papers but cannot pull back a paper already
    # dropped by the per-year cap. Acceptable trade-off given award papers are
    # almost always also high-citation and thus survive the cap.
    selected: list[Paper] = []
    for year in sorted(by_year.keys()):
        papers_in_year = by_year[year]
        papers_in_year.sort(
            key=lambda p: (_AWARD_WEIGHT.get(p.award, 0), p.citation_count),
            reverse=True,
        )
        selected.extend(papers_in_year[:max_per_year])

    return selected


def _identify_awards(
    papers: list[Paper],
    model: str = "sonnet",
    cache: DiskCache | None = None,
    no_cache: bool = False,
    backend: str = "claude_cli",
) -> int:
    """Use LLM to identify paper awards. Modifies papers in-place. Returns count."""
    if not papers:
        return 0

    # Build paper list for prompt
    lines = []
    for p in papers:
        year = p.published[:4] if p.published else "?"
        venue = f" ({p.venue})" if p.venue else ""
        lines.append(f"- [{year}] {p.title}{venue}")

    prompt = AWARD_IDENTIFICATION_PROMPT.format(papers_list="\n".join(lines))
    response = call_llm(prompt, model=model, cache=cache, no_cache=no_cache, backend=backend)
    result = parse_json_response(response, backend=backend)

    if not result or "awards" not in result:
        return 0

    # Build lookup by normalized title
    paper_by_title: dict[str, Paper] = {}
    for p in papers:
        paper_by_title[p.title.lower().strip()] = p

    valid_awards = set(_AWARD_WEIGHT.keys())
    count = 0
    for entry in result["awards"]:
        # Guard against malformed LLM output (e.g. a string/list entry where a
        # dict is expected); skip anything that isn't a dict with a title.
        if not isinstance(entry, dict) or not entry.get("title"):
            continue
        title = (entry.get("title") or "").lower().strip()
        award = entry.get("award", "")
        if title in paper_by_title and award in valid_awards:
            paper_by_title[title].award = award
            count += 1

    return count


def analyze_researcher(
    name: str,
    mode: str = "fast",
    model: str = "sonnet",
    cache: DiskCache | None = None,
    no_cache: bool = False,
    s2_api_key: str = "",
    backend: str = "claude_cli",
    affiliation: str = "",
    paper_hint: str = "",
    author_id_hint: str = "",
) -> ResearcherProfile:
    """Analyze a single researcher: fetch data, run LLM analysis, compute score."""
    print(f"\n{'='*60}")
    print(f"  分析研究者: {name} (模式: {mode})")
    print(f"{'='*60}")

    # 1. Fetch papers from ArXiv
    print(f"  [1/6] 从 ArXiv 获取论文...")
    arxiv_papers = search_papers_by_author(name, max_results=100, cache=cache)
    print(f"        找到 {len(arxiv_papers)} 篇 ArXiv 论文")

    # 2. Fetch metrics from Semantic Scholar (three-tier resolution)
    print(f"  [2/6] 从 Semantic Scholar 获取指标...")
    s2_author = None
    # Tier 1: Direct author ID
    if author_id_hint:
        print(f"        Tier 1: 直接使用作者 ID {author_id_hint}")
        s2_author = get_author_by_id(author_id_hint, api_key=s2_api_key, cache=cache)
    # Tier 2: Paper reverse lookup
    if not s2_author and paper_hint:
        print(f"        Tier 2: 通过论文反查 ({paper_hint})")
        s2_author = resolve_author_by_paper(name, paper_hint, api_key=s2_api_key, cache=cache)
    # Tier 3: Name search (original logic, scoring already fixed)
    if not s2_author:
        if author_id_hint or paper_hint:
            print(f"        Tier 3: 回退到名字搜索")
        s2_author = search_author(name, affiliation=affiliation, api_key=s2_api_key, cache=cache)
    s2_papers: list[dict] = []
    if s2_author:
        author_id = s2_author.get("authorId", "")
        if author_id:
            s2_papers = get_author_papers(author_id, api_key=s2_api_key, cache=cache)
        metrics = build_metrics(s2_author, s2_papers)
        print(f"        h-index={metrics.h_index}, 引用={metrics.total_citations}, "
              f"论文={metrics.paper_count}")
    else:
        from research.models import ResearcherMetrics
        metrics = ResearcherMetrics()
        print(f"        警告: 未在 Semantic Scholar 找到此作者")

    # Select papers by year (S2 as primary, ArXiv enriches)
    papers = _select_papers_by_year(arxiv_papers, s2_papers)

    # Early return if no papers found from any source
    if not papers and not s2_papers and not arxiv_papers:
        print(f"        错误: 未找到任何论文。请检查姓名拼写是否正确。")
        if not affiliation:
            print(f"        提示: 对于常见姓名，可尝试 --affiliation 参数帮助区分同名作者")
        return ResearcherProfile(
            name=name,
            metrics=metrics,
            papers=[],
            analysis={"error": "no_papers_found",
                      "message": f"No papers found for '{name}'. Check spelling or try --affiliation."},
            tier=ResearcherTier.EARLY_CAREER,
            tier_score=0.0,
            mode=mode,
            fetched_at=datetime.now().isoformat(),
        )

    # 3. Identify awards via LLM
    print(f"  [3/6] 识别论文奖项（Best Paper / Spotlight 等）...")
    award_count = _identify_awards(papers, model=model, cache=cache, no_cache=no_cache, backend=backend)
    print(f"        识别到 {award_count} 篇获奖论文")

    # Re-sort after awards are assigned (award weight may change ordering within years)
    papers = _resort_after_awards(papers)

    # 4. Detailed mode: download full text (HTML first, PDF fallback)
    if mode == "detailed":
        print(f"  [4/6] 下载论文全文（HTML 优先，PDF 后备）...")
        papers_for_download = [p for p in papers if p.arxiv_id]
        for i, paper in enumerate(papers_for_download):
            if not paper.full_text:
                print(f"        下载 ({i+1}/{len(papers_for_download)}): {paper.title[:60]}...")
                paper.full_text = download_fulltext(
                    paper.arxiv_id, paper.pdf_url, cache=cache
                )
        papers_with_text = [p for p in papers_for_download if p.full_text]
        print(f"        成功提取 {len(papers_with_text)} 篇全文")
        # Cap full text embedded in the prompt so prolific researchers don't
        # overflow the model context window (top-N by citations + char budget).
        budgeted = _budget_full_text_papers(papers_with_text)
        if len(budgeted) < len(papers_with_text):
            print(f"        全文上下文预算：保留 {len(budgeted)}/{len(papers_with_text)} 篇")
        papers_with_text = budgeted
    else:
        print(f"  [4/6] 快速模式，跳过全文下载")
        papers_with_text = []

    # 5. LLM Analysis
    print(f"  [5/6] 调用 LLM 分析研究轨迹...")
    papers_dicts = [p.to_dict() for p in papers]

    if mode == "detailed" and papers_with_text:
        prompt = TRAJECTORY_ANALYSIS_DETAILED_PROMPT.format(
            name=name,
            affiliation=metrics.current_affiliation or "未知",
            h_index=metrics.h_index,
            total_citations=metrics.total_citations,
            recent_citations=metrics.recent_citations_5yr,
            paper_count=metrics.paper_count,
            top_venue_count=metrics.top_venue_count,
            first_year=metrics.first_paper_year,
            latest_year=metrics.latest_paper_year,
            papers_text=format_papers_for_prompt(papers_dicts, mode="detailed"),
            full_text_section=format_full_texts(
                [p.to_dict() for p in papers_with_text]
            ),
        )
    else:
        prompt = TRAJECTORY_ANALYSIS_PROMPT.format(
            name=name,
            affiliation=metrics.current_affiliation or "未知",
            h_index=metrics.h_index,
            total_citations=metrics.total_citations,
            recent_citations=metrics.recent_citations_5yr,
            paper_count=metrics.paper_count,
            top_venue_count=metrics.top_venue_count,
            first_year=metrics.first_paper_year,
            latest_year=metrics.latest_paper_year,
            papers_text=format_papers_for_prompt(papers_dicts, mode=mode),
        )

    llm_response = call_llm(prompt, model=model, cache=cache, no_cache=no_cache, backend=backend)
    analysis = parse_json_response(llm_response, backend=backend)
    if not analysis:
        print(f"        警告: LLM 分析结果解析失败")
        analysis = {"error": "JSON parse failed", "raw_response": llm_response[:2000]}

    # 6. Compute tier score
    print(f"  [6/6] 计算评分...")
    tier_score = compute_tier_score(metrics)
    tier = classify_tier(tier_score)
    print(f"        评分: {tier_score}/100 → {tier.label_en}")

    s2_id = s2_author.get("authorId", "") if s2_author else ""
    profile = ResearcherProfile(
        name=name,
        metrics=metrics,
        papers=papers,
        analysis=analysis,
        s2_author_id=s2_id,
        tier=tier,
        tier_score=tier_score,
        mode=mode,
        fetched_at=datetime.now().isoformat(),
    )

    return profile


def _resort_after_awards(papers: list[Paper]) -> list[Paper]:
    """Re-sort papers by year (asc), then award weight + citations (desc) within year."""
    by_year: dict[int, list[Paper]] = defaultdict(list)
    for p in papers:
        year = int(p.published[:4]) if p.published and p.published[:4].isdigit() else 0
        by_year[year].append(p)

    result: list[Paper] = []
    for year in sorted(by_year.keys()):
        year_papers = by_year[year]
        year_papers.sort(
            key=lambda p: (_AWARD_WEIGHT.get(p.award, 0), p.citation_count),
            reverse=True,
        )
        result.extend(year_papers)
    return result


def _normalize_name(name: str) -> str:
    """Normalize a name for dedup comparison."""
    return " ".join(name.lower().strip().split())


def _merge_student_lists(
    homepage_students: list[StudentCandidate],
    coauth_students: list[StudentCandidate],
) -> list[StudentCandidate]:
    """Merge homepage and co-authorship student lists, deduplicating by name."""
    merged: dict[str, StudentCandidate] = {}

    # Homepage students first (primary source)
    for s in homepage_students:
        key = _normalize_name(s.name)
        merged[key] = s

    # Merge co-authorship data
    for s in coauth_students:
        key = _normalize_name(s.name)
        if key in merged:
            # Overlap: merge co-authorship stats into homepage entry
            existing = merged[key]
            existing.source = "both"
            existing.coauthor_count = s.coauthor_count
            existing.first_author_count = s.first_author_count
            existing.collab_start_year = s.collab_start_year
            existing.collab_end_year = s.collab_end_year
            existing.relationship_score = s.relationship_score
            if not existing.research_direction and s.research_direction:
                existing.research_direction = s.research_direction
        else:
            s.source = "coauthorship"
            merged[key] = s

    # Sort: "both" first, then by relationship_score desc, then homepage, then coauthorship
    source_order = {"both": 0, "homepage": 1, "coauthorship": 2}
    result = sorted(
        merged.values(),
        key=lambda s: (source_order.get(s.source, 3), -s.relationship_score),
    )
    return result


def discover_students(
    profile: ResearcherProfile,
    max_students: int = 10,
    model: str = "sonnet",
    cache: DiskCache | None = None,
    no_cache: bool = False,
    s2_api_key: str = "",
    backend: str = "claude_cli",
    homepage_url: str = "",
) -> list[dict[str, Any]]:
    """Discover potential students via homepage (primary) + co-authorship (supplement)."""
    from research.homepage_discovery import discover_students_from_homepage

    print(f"\n  发现学生: {profile.name}")

    # Phase 1: Homepage discovery (primary)
    # Reuse stored S2 author ID if available, avoiding re-disambiguation
    if profile.s2_author_id:
        s2_author = get_author_by_id(profile.s2_author_id, api_key=s2_api_key, cache=cache)
    else:
        s2_author = search_author(profile.name, api_key=s2_api_key, cache=cache)
    s2_homepage = ""
    if s2_author:
        s2_homepage = s2_author.get("homepage") or s2_author.get("url") or ""

    affiliation = profile.metrics.current_affiliation or ""

    print(f"  [Phase 1] 主页学生发现...")
    homepage_students = discover_students_from_homepage(
        name=profile.name,
        affiliation=affiliation,
        s2_homepage=s2_homepage,
        homepage_url=homepage_url,
        model=model,
        cache=cache,
        backend=backend,
    )

    # Phase 2: Co-authorship analysis (supplement, skip if homepage already has enough)
    coauth_students: list[StudentCandidate] = []
    if len(homepage_students) >= max_students:
        print(f"  [Phase 2] 跳过（主页已发现 {len(homepage_students)} 个学生）")
    elif s2_author:
        print(f"  [Phase 2] 共著关系分析...")
        author_id = s2_author.get("authorId", "")
        if author_id:
            s2_papers = get_author_papers(author_id, api_key=s2_api_key, cache=cache)
            coauthor_data = get_coauthor_data(author_id, s2_papers, profile.name)
            coauth_students = score_student_candidates(coauthor_data, max_candidates=max_students)
            for c in coauth_students:
                c.source = "coauthorship"

    # Phase 3: Merge & deduplicate
    print(f"  [Phase 3] 合并去重...")
    candidates = _merge_student_lists(homepage_students, coauth_students)
    candidates = candidates[:max_students]

    if not candidates:
        print(f"  未发现学生候选人")
        return []

    hp_count = sum(1 for c in candidates if c.source == "homepage")
    ca_count = sum(1 for c in candidates if c.source == "coauthorship")
    both_count = sum(1 for c in candidates if c.source == "both")
    print(f"  发现 {len(candidates)} 个学生 (主页: {hp_count}, 共著: {ca_count}, 两者: {both_count})")

    # Phase 4: LLM evaluation (enrich with research direction for coauthorship candidates)
    coauth_only = [c for c in candidates if c.source in ("coauthorship", "both") and c.coauthor_count > 0]
    if coauth_only:
        themes = profile.analysis.get("research_themes", [])
        candidates_dicts = [c.to_dict() for c in coauth_only]
        prompt = STUDENT_EVALUATION_PROMPT.format(
            advisor_name=profile.name,
            research_themes=", ".join(themes) if themes else "未知",
            candidates_text=format_candidates_for_prompt(candidates_dicts),
        )

        llm_response = call_llm(prompt, model=model, cache=cache, no_cache=no_cache, backend=backend)
        eval_result = parse_json_response(llm_response, backend=backend)

        if eval_result and "students" in eval_result:
            # Guard against malformed LLM output: only index dict entries that
            # carry a truthy "name"; skip strings/lists/empty names.
            eval_by_name = {
                s["name"].lower(): s
                for s in eval_result["students"]
                if isinstance(s, dict) and s.get("name")
            }
            for c in candidates:
                ev = eval_by_name.get(c.name.lower(), {})
                if ev.get("research_direction") and not c.research_direction:
                    c.research_direction = ev["research_direction"]

    profile.inferred_students = candidates
    return [c.to_dict() for c in candidates]


def _parse_batch_line(line: str) -> tuple[str, str, str]:
    """Parse a batch file line into (name, paper_hint, author_id_hint).

    Formats:
        Sergey Levine                         → ("Sergey Levine", "", "")
        Pieter Abbeel | arxiv:2301.12597      → ("Pieter Abbeel", "2301.12597", "")
        Chelsea Finn | s2:2072701             → ("Chelsea Finn", "", "2072701")
        Yuke Zhu | Soft Actor-Critic          → ("Yuke Zhu", "Soft Actor-Critic", "")
    """
    import re as _re
    parts = [p.strip() for p in line.split("|", 1)]
    name = parts[0]
    paper_hint = ""
    author_id_hint = ""
    if len(parts) > 1:
        hint = parts[1]
        if hint.lower().startswith("arxiv:"):
            paper_hint = hint[6:].strip()
        elif hint.lower().startswith("s2:"):
            author_id_hint = hint[3:].strip()
        elif hint.startswith("10.") or _re.match(r"\d{4}\.\d+", hint):
            paper_hint = hint
        else:
            # Treat as paper title
            paper_hint = hint
    return name, paper_hint, author_id_hint


def run_analysis(
    seed_names: list[str],
    mode: str = "fast",
    depth: int = 0,
    max_students: int = 10,
    model: str = "sonnet",
    cache: DiskCache | None = None,
    no_cache: bool = False,
    output_dir: str = "",
    profiles_dir: str = "",
    reports_dir: str = "",
    s2_api_key: str = "",
    backend: str = "claude_cli",
    homepage_url: str = "",
    affiliation: str = "",
    paper_hint: str = "",
    author_id_hint: str = "",
    hints: dict[str, tuple[str, str]] | None = None,
) -> list[ResearcherProfile]:
    """Main entry point: BFS recursive analysis of researchers."""
    from pathlib import Path
    from research.config import resolve_profiler_paths

    # Explicit dir params take priority; fall back to config-based defaults
    if profiles_dir or reports_dir:
        defaults = resolve_profiler_paths({"output_dir": output_dir} if output_dir else {})
        prof_dir = Path(profiles_dir) if profiles_dir else defaults["profiles"]
        rep_dir = Path(reports_dir) if reports_dir else defaults["reports"]
    elif output_dir:
        prof_dir = Path(output_dir) / "profiles"
        rep_dir = Path(output_dir) / "reports"
    else:
        defaults = resolve_profiler_paths({})
        prof_dir = defaults["profiles"]
        rep_dir = defaults["reports"]

    # BFS queue: (name, current_depth)
    queue: deque[tuple[str, int]] = deque()
    visited: set[str] = set()
    all_profiles: list[ResearcherProfile] = []

    for name in seed_names:
        queue.append((name.strip(), 0))

    while queue:
        name, current_depth = queue.popleft()
        name_key = name.lower()

        if name_key in visited:
            continue
        visited.add(name_key)

        print(f"\n{'#'*60}")
        print(f"  深度 {current_depth}/{depth}: {name}")
        print(f"{'#'*60}")

        try:
            # Only pass affiliation/hints for seed researchers (depth 0)
            aff = affiliation if current_depth == 0 else ""
            ph, aid = "", ""
            if current_depth == 0:
                if hints and name in hints:
                    ph, aid = hints[name]
                elif len(seed_names) == 1:
                    # The global --paper/--author-id hint is unambiguous only when
                    # there's a single seed; with multiple seeds it would wrongly
                    # apply the same hint to every name, so fall back to name search.
                    ph, aid = paper_hint, author_id_hint
            profile = analyze_researcher(
                name, mode=mode, model=model,
                cache=cache, no_cache=no_cache, s2_api_key=s2_api_key,
                backend=backend, affiliation=aff,
                paper_hint=ph, author_id_hint=aid,
            )
        except Exception as e:
            logger.error(f"分析 {name} 失败: {e}")
            print(f"  错误: 分析 {name} 失败 — {e}")
            continue

        # Discover students if depth allows
        if current_depth < depth:
            try:
                # Only pass explicit homepage_url for seed researchers (depth 0)
                hp_url = homepage_url if current_depth == 0 else ""
                student_candidates = discover_students(
                    profile, max_students=max_students,
                    model=model, cache=cache, no_cache=no_cache,
                    s2_api_key=s2_api_key, backend=backend,
                    homepage_url=hp_url,
                )
                for sc in student_candidates:
                    sc_name = sc.get("name", "")
                    if sc_name and sc_name.lower() not in visited:
                        queue.append((sc_name, current_depth + 1))
            except Exception as e:
                logger.error(f"发现学生失败 {name}: {e}")
                print(f"  警告: 发现学生时出错 — {e}")

        # Save outputs
        save_profile(profile, prof_dir)
        render_report(profile, rep_dir)
        all_profiles.append(profile)

    # Summary
    print(f"\n{'='*60}")
    print(f"  分析完成! 共分析 {len(all_profiles)} 位研究者")
    print(f"{'='*60}")
    for p in all_profiles:
        print(f"  {p.tier.label_en:6s} ({p.tier_score:5.1f}) | {p.name}")
    print()

    return all_profiles
