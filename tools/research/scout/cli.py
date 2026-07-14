"""CLI commands and argparse entry point for Research Scout."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

from common.io import atomic_write
from common.json_utils import try_repair_result as _try_repair_result
from common.hugo import run_hugo_update
from common.site_staging import resolve_site_content_dir

from scout.config import (
    PROJECTS_DIR,
    CACHE_DIR,
    REPORTS_DIR,
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_HUGO_SITE,
    MAX_PAPERS_PER_PROJECT,
    TOP_PAPERS_IN_REPORT,
    MAX_HIGH_RELEVANCE,
    DEFAULT_LANGUAGE,
    load_scout_config,
    resolve_param,
    get_hugo_site,
    get_reports_dir,
    setup_logging,
    get_logger,
    _SCOUT_CONFIG_PATH,
)
from scout.project import (
    create_project,
    create_project_from_overview,
    create_project_from_query,
    load_project,
    save_project,
    load_all_projects,
)
from scout.search import (
    paper_id as _paper_id,
    paper_url as _paper_url,
    search_arxiv,
    search_arxiv_conference,
    search_arxiv_author,
    search_source,
    load_search_cache,
    save_search_cache,
    load_known_paper_ids,
)
from scout.evaluate import (
    call_scout_llm,
    evaluate_papers_for_project,
    suggest_directions,
    analyze_citations,
)
from scout.report import (
    generate_daily_report,
    generate_report_markdown,
    save_report,
    generate_hugo_post,
    append_literature_note,
)

logger = get_logger()


# ─── CLI commands ────────────────────────────────────────────────────

def cmd_init(args):
    """Create a new project."""
    project_id = args.name
    if not re.match(r"^[a-z0-9][a-z0-9_-]*$", project_id):
        print("[error] 项目 ID 只允许小写字母、数字、连字符和下划线，且以字母或数字开头")
        sys.exit(1)

    if args.from_overview:
        api = getattr(args, "api", None) or "ollama"
        timeout = getattr(args, "timeout", None) or 600
        create_project_from_overview(project_id, args.from_overview, api, timeout)
        return

    title = args.title or project_id
    keywords = args.keywords or []
    categories = args.categories or []
    questions = args.questions or []

    create_project(project_id, title, keywords, categories, questions)


def cmd_list(args):
    """List all projects."""
    show_ask = getattr(args, "all", False)
    projects = load_all_projects()
    if not show_ask:
        projects = [p for p in projects if p.get("status") != "ask"]
    if not projects:
        if show_ask:
            print("(暂无项目，使用 init 或 ask 创建)")
        else:
            print("(暂无项目，使用 init 创建。使用 list --all 查看 ask 项目)")
        return

    print(f"共 {len(projects)} 个项目:\n")
    for pj in projects:
        status = pj.get("status", "unknown")
        status_icon = {"active": "[active]", "paused": "[paused]",
                       "completed": "[done]", "ask": "[ask]"}.get(status, f"[{status}]")
        last_search = pj.get("last_searched", "never")
        kw_count = len(pj.get("search_keywords", []))
        cat_count = len(pj.get("arxiv_categories", []))
        sources = pj.get("sources", ["arxiv"])

        print(f"  {status_icon:10s} {pj['id']}")
        print(f"             {pj.get('title', '')}")
        print(f"             keywords: {kw_count}, categories: {cat_count}, "
              f"sources: {', '.join(sources)}, last search: {last_search}")
        print()


def cmd_search(args):
    """Search papers (no LLM evaluation)."""
    conference = getattr(args, "conference", None)
    author = getattr(args, "author", None)
    no_cache = getattr(args, "no_cache", False)
    today = date.today()

    if conference and author:
        logger.error("--conference 和 --author 不能同时使用")
        sys.exit(1)

    if conference:
        project = load_project(args.project) if args.project else None
        max_results = resolve_param(args, project, "max_results", MAX_PAPERS_PER_PROJECT)

        if not no_cache and project:
            cached = load_search_cache(project, today, conference)
            if cached is not None:
                logger.info("会议搜索缓存命中: %s (%d 篇)", conference, len(cached))
                for p in cached[:5]:
                    print(f"    [{_paper_id(p)}] {p['title'][:80]}")
                return

        papers = search_arxiv_conference(conference, project, max_results)

        if project:
            save_search_cache(project, today, papers, conference)

        if papers:
            print(f"\n  最新 5 篇:")
            for p in papers[:5]:
                print(f"    [{_paper_id(p)}] {p['title'][:80]}")
            print()
        return

    if author:
        project = load_project(args.project) if args.project else None
        max_results = resolve_param(args, project, "max_results", MAX_PAPERS_PER_PROJECT)
        lookback = getattr(args, "lookback_days", None)

        if not no_cache and project:
            cached = load_search_cache(project, today, author=author)
            if cached is not None:
                logger.info("作者搜索缓存命中: %s (%d 篇)", author, len(cached))
                for p in cached[:5]:
                    print(f"    [{_paper_id(p)}] {p['title'][:80]}")
                return

        papers = search_arxiv_author(author, project, max_results,
                                     lookback_days=lookback)

        if project:
            save_search_cache(project, today, papers, author=author)

        if papers:
            print(f"\n  最新 5 篇:")
            for p in papers[:5]:
                print(f"    [{_paper_id(p)}] {p['title'][:80]}")
            print()
        return

    # Regular multi-source search
    if args.project:
        projects = [load_project(args.project)]
    else:
        projects = load_all_projects(status_filter="active")
        if not projects:
            logger.warning("没有 active 状态的项目")
            return

    cli_sources = getattr(args, "source", None)

    for pj in projects:
        lookback = resolve_param(args, pj, "lookback_days", DEFAULT_LOOKBACK_DAYS)
        max_results = resolve_param(args, pj, "max_results", MAX_PAPERS_PER_PROJECT)
        sources = cli_sources or pj.get("sources", ["arxiv"])

        all_papers = []
        for src in sources:
            papers = search_source(pj, src, lookback, max_results, no_cache, today)
            all_papers.extend(papers)

        pj["last_searched"] = today.isoformat()
        save_project(pj)

        if all_papers:
            print(f"\n  {pj['id']}: {len(all_papers)} 篇 (sources: {', '.join(sources)})")
            print(f"  最新 5 篇:")
            for p in all_papers[:5]:
                src_tag = f"[{p.get('source', 'arxiv')}]" if p.get("source", "arxiv") != "arxiv" else ""
                print(f"    {src_tag}[{_paper_id(p)}] {p['title'][:80]}")
            print()


def run_evaluation_pipeline(
    pj: dict,
    papers: list[dict],
    *,
    api: str = "claude_cli",
    timeout: int = 600,
    no_cache: bool = False,
    language: str = DEFAULT_LANGUAGE,
    insight: bool = False,
    insight_top_n: int | None = None,
) -> dict:
    """Run 3-stage evaluation + citation analysis + direction suggestions on papers.

    If insight=True, also runs Stage 4 (insight analysis) + Stage 5 (OpenReview reviews)
    and generates a writing guide synthesis.

    Returns a project_data dict suitable for report generation:
    {"project": pj, "high_relevance": [...], "low_relevance": [...],
     "screening_stats": {...}, "directions": [...], "writing_guide": {...}}
    """
    today = date.today()

    # Stage 1-2: Three-stage LLM evaluation
    logger.info("评估 %d 篇论文 (三阶段管线)...", len(papers))
    eval_result = evaluate_papers_for_project(
        pj, papers, api=api, timeout=timeout,
        use_cache=not no_cache, language=language,
    )

    high_papers = eval_result["high_relevance"]
    low_papers = eval_result["low_relevance"]
    stats = eval_result["screening_stats"]

    # Stage 3: Citation impact analysis (top 5 papers)
    from common.cache import DiskCache as _DiskCache
    citation_cache = None if no_cache else _DiskCache(CACHE_DIR)
    s2_key = load_scout_config().get("semantic_scholar_api_key", "")
    citation_top = high_papers[:5]
    if citation_top:
        logger.info("Stage 3: 引用影响分析 (%d 篇高分论文)...", len(citation_top))
        for ci, cp in enumerate(citation_top):
            cpid = _paper_id(cp)
            logger.info("  [%d/%d] 分析引用: %s", ci + 1, len(citation_top), cpid)
            try:
                ca = analyze_citations(cp, api=api, timeout=timeout,
                                       cache_obj=citation_cache, api_key=s2_key)
                if ca:
                    cp["citation_analysis"] = ca
                    logger.info("    引用: %d, 参考文献: %d",
                                ca.get("total_forward_citations", 0),
                                ca.get("total_references", 0))
            except Exception as e:
                logger.warning("  引用分析失败 %s: %s", cpid, e)

    # Direction suggestions
    top_papers = [e for e in high_papers if e.get("composite_score", 0) >= 2.5]
    directions = []
    if top_papers:
        logger.info("生成研究方向建议 (基于 %d 篇高分论文)...", len(top_papers))
        directions = suggest_directions(pj, top_papers, api=api, timeout=timeout, language=language)

    # Append literature notes
    top_for_notes = high_papers[:3]
    if top_for_notes:
        append_literature_note(pj["id"], top_for_notes, today)

    # Stage 4+5: Insight analysis + OpenReview reviews (opt-in)
    writing_guide = {}
    if insight and high_papers:
        from scout.insight import run_insight_analysis
        _, writing_guide = run_insight_analysis(
            high_papers, pj,
            api=api, timeout=timeout, language=language,
            top_n=insight_top_n, use_cache=not no_cache,
        )

    return {
        "project": pj,
        "high_relevance": high_papers,
        "low_relevance": low_papers,
        "screening_stats": stats,
        "directions": directions,
        "writing_guide": writing_guide,
    }


def finalize_report(
    projects_data: dict,
    today: date,
    *,
    reports_dir: Path | None = None,
    deploy: bool = False,
    hugo_site: Path | None = None,
    api: str = "claude_cli",
) -> None:
    """Generate report from projects_data and optionally deploy to Hugo."""
    if reports_dir is None:
        reports_dir = REPORTS_DIR
    report = generate_daily_report(projects_data, today)
    markdown = generate_report_markdown(report)
    save_report(report, markdown, reports_dir, today)

    if deploy:
        if hugo_site is None:
            hugo_site = DEFAULT_HUGO_SITE
        if not hugo_site.exists():
            logger.error("Hugo 站点目录不存在: %s", hugo_site)
            return
        generate_hugo_post(markdown, today, hugo_site, api=api)
        run_hugo_update(hugo_site)


def cmd_report(args):
    """Full pipeline: search -> 3-stage evaluation -> direction suggestions -> daily report."""
    conference = getattr(args, "conference", None)
    author = getattr(args, "author", None)
    if conference and author:
        logger.error("--conference 和 --author 不能同时使用")
        sys.exit(1)
    api = args.api or "ollama"
    timeout = args.timeout or 600
    no_cache = getattr(args, "no_cache", False)
    language = resolve_param(args, None, "language", DEFAULT_LANGUAGE)
    today = date.today()
    reports_dir = get_reports_dir(args)

    if args.project:
        projects = [load_project(args.project)]
    else:
        projects = load_all_projects(status_filter="active")
        if not projects:
            logger.warning("没有 active 状态的项目")
            return

    cli_sources = getattr(args, "source", None)
    projects_data = {}

    for pj in projects:
        pid = pj["id"]
        lookback = resolve_param(args, pj, "lookback_days", DEFAULT_LOOKBACK_DAYS)
        max_results = resolve_param(args, pj, "max_results", MAX_PAPERS_PER_PROJECT)

        print(f"\n{'='*60}")
        print(f"项目: {pj['title']} ({pid})")
        print(f"{'='*60}")

        # Step 1: Search
        papers = None
        if conference:
            if not no_cache:
                papers = load_search_cache(pj, today, conference)
                if papers is not None:
                    logger.info("会议搜索缓存命中: %d 篇", len(papers))
            if papers is None:
                papers = search_arxiv_conference(conference, pj, max_results)
                save_search_cache(pj, today, papers, conference)
        elif author:
            author_lookback = getattr(args, "lookback_days", None)
            if not no_cache:
                papers = load_search_cache(pj, today, author=author)
                if papers is not None:
                    logger.info("作者搜索缓存命中: %d 篇", len(papers))
            if papers is None:
                papers = search_arxiv_author(author, pj, max_results,
                                             lookback_days=author_lookback)
                save_search_cache(pj, today, papers, author=author)
        else:
            sources = cli_sources or pj.get("sources", ["arxiv"])
            papers = []
            for src in sources:
                src_papers = search_source(pj, src, lookback, max_results, no_cache, today)
                papers.extend(src_papers)

            pj["last_searched"] = today.isoformat()
            save_project(pj)

        if not papers:
            logger.info("未找到论文，跳过")
            continue

        # Steps 2-5: Evaluation pipeline (+ optional insight)
        do_insight = getattr(args, "insight", False)
        insight_top_n = getattr(args, "insight_top_n", None)
        project_data = run_evaluation_pipeline(
            pj, papers, api=api, timeout=timeout,
            no_cache=no_cache, language=language,
            insight=do_insight, insight_top_n=insight_top_n,
        )
        projects_data[pid] = project_data

    if not projects_data:
        logger.warning("没有项目产生结果")
        return

    # Steps 6-7: Report + deploy
    deploy = getattr(args, "deploy", False)
    hugo_site = get_hugo_site(args) if deploy else None
    finalize_report(projects_data, today, reports_dir=reports_dir,
                    deploy=deploy, hugo_site=hugo_site, api=api)


def cmd_ask(args):
    """Natural language search: parse intent -> create project -> search -> evaluate -> report."""
    from scout.ask import parse_ask_intent, route_search

    query = " ".join(args.query)
    if not query.strip():
        logger.error("请提供自然语言查询")
        sys.exit(1)

    api = args.api or "ollama"
    timeout = args.timeout or 600
    no_cache = getattr(args, "no_cache", False)
    language = resolve_param(args, None, "language", DEFAULT_LANGUAGE)
    today = date.today()
    reports_dir = get_reports_dir(args)

    # Step 1: Parse natural language intent
    print(f"\n{'='*60}")
    print(f"解析查询: {query}")
    print(f"{'='*60}")

    try:
        plan = parse_ask_intent(query, api=api, timeout=timeout)
    except ValueError as e:
        logger.error("查询解析失败: %s", e)
        sys.exit(1)

    logger.info("搜索计划:")
    logger.info("  模式: %s", plan["search_mode"])
    logger.info("  关键词: %s", plan["search_keywords"])
    logger.info("  分类: %s", plan["arxiv_categories"])
    logger.info("  数据源: %s", plan["sources"])
    if plan.get("author"):
        logger.info("  作者: %s", plan["author"])
    if plan.get("conference"):
        logger.info("  会议: %s", plan["conference"])
    logger.info("  回溯天数: %d", plan["lookback_days"])

    # Step 2: Create project
    pj, project_dir = create_project_from_query(plan)

    print(f"\n项目: {pj['title']} ({pj['id']})")

    # Step 3: Search
    papers = route_search(plan, pj, no_cache=no_cache, today=today)
    if papers:
        save_project(pj)  # persist last_searched set by route_search
    if not papers:
        logger.warning("未找到论文，清理临时项目: %s", pj["id"])
        import shutil
        shutil.rmtree(project_dir, ignore_errors=True)
        return

    # Step 4: Evaluation pipeline (+ optional insight)
    do_insight = getattr(args, "insight", False)
    insight_top_n = getattr(args, "insight_top_n", None)
    project_data = run_evaluation_pipeline(
        pj, papers, api=api, timeout=timeout,
        no_cache=no_cache, language=language,
        insight=do_insight, insight_top_n=insight_top_n,
    )

    # Step 5: Report + deploy
    projects_data = {pj["id"]: project_data}
    deploy = getattr(args, "deploy", False)
    hugo_site = get_hugo_site(args) if deploy else None
    finalize_report(projects_data, today, reports_dir=reports_dir,
                    deploy=deploy, hugo_site=hugo_site, api=api)


def cmd_profile(args):
    """Analyze researcher: delegates to modular profiler package."""
    from research.analysis import run_analysis as _run_analysis
    from common.cache import DiskCache as _DiskCache
    from research.config import load_config as _load_profiler_config, resolve_profiler_paths

    cfg = _load_profiler_config()

    from research.analysis import _parse_batch_line

    names = list(args.names) if args.names else []
    batch_hints: dict[str, tuple[str, str]] = {}
    if args.from_file:
        fpath = Path(args.from_file)
        if not fpath.exists():
            logger.error("文件不存在: %s", fpath)
            sys.exit(1)
        for line in fpath.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                parsed_name, ph, aid = _parse_batch_line(line)
                names.append(parsed_name)
                if ph or aid:
                    batch_hints[parsed_name] = (ph, aid)

    if not names:
        logger.error("请提供研究者姓名或使用 --from-file")
        sys.exit(1)

    mode = args.mode or cfg.get("default_mode", "fast")
    depth = args.depth if args.depth is not None else cfg.get("default_depth", 0)
    max_students = args.max_students or cfg.get("max_students", 10)
    model = args.model or cfg.get("model", "sonnet")
    no_cache = getattr(args, "no_cache", False)

    backend = args.api or load_scout_config().get("default_api", "ollama")

    profiler_paths = resolve_profiler_paths(cfg)
    cache = None if no_cache else _DiskCache(profiler_paths["cache"])
    s2_key = cfg.get("semantic_scholar_api_key", "")

    homepage_url = getattr(args, "homepage", "") or ""
    affiliation = getattr(args, "affiliation", "") or ""
    paper_hint = getattr(args, "paper", "") or ""
    author_id_hint = getattr(args, "author_id", "") or ""

    profiles = _run_analysis(
        seed_names=names,
        mode=mode,
        depth=depth,
        max_students=max_students,
        model=model,
        cache=cache,
        no_cache=no_cache,
        profiles_dir=str(profiler_paths["profiles"]),
        reports_dir=str(profiler_paths["reports"]),
        s2_api_key=s2_key,
        backend=backend,
        homepage_url=homepage_url,
        affiliation=affiliation,
        paper_hint=paper_hint,
        author_id_hint=author_id_hint,
        hints=batch_hints if batch_hints else None,
    )

    if getattr(args, "deploy", False) and profiles:
        from research.output import deploy_to_hugo
        hugo_site = Path(args.hugo_site) if args.hugo_site else get_hugo_site(args)
        if hugo_site.exists():
            for p in profiles:
                deploy_to_hugo(p, hugo_site)
            run_hugo_update(hugo_site)
        else:
            logger.warning("Hugo 站点不存在: %s，跳过部署", hugo_site)


def cmd_citations(args):
    """Citation graph analysis: view paper citations and references."""
    from research.apis.semantic_scholar import (
        get_paper_by_id, get_paper_citations, get_paper_references,
    )
    from research.prompts import CITATION_IMPACT_PROMPT

    no_cache = getattr(args, "no_cache", False)
    from common.cache import DiskCache as _DiskCache
    cache = None if no_cache else _DiskCache(CACHE_DIR)
    scout_cfg = load_scout_config()
    api = args.api or scout_cfg.get("default_api", "ollama")
    timeout = args.timeout or 600
    top_n = args.top_n or 10
    paper_id_arg = args.paper_id

    s2_key = scout_cfg.get("semantic_scholar_api_key", "")

    # Step 1: Resolve to S2 paper
    print(f"\n查找论文: {paper_id_arg}")
    s2_paper = get_paper_by_id(paper_id_arg, api_key=s2_key, cache=cache)
    if not s2_paper:
        logger.error("无法在 Semantic Scholar 找到论文: %s", paper_id_arg)
        sys.exit(1)

    s2_id = s2_paper["paperId"]
    title = s2_paper.get("title", "")
    total_cites = s2_paper.get("citationCount") or 0
    abstract = s2_paper.get("abstract", "")

    print(f"标题: {title}")
    print(f"被引次数: {total_cites}")
    print()

    # Step 2: Forward citations
    print(f"获取前向引用 (top {top_n})...")
    forward = get_paper_citations(s2_id, limit=top_n, api_key=s2_key, cache=cache)

    if forward:
        print(f"\n### 引用此论文的高引后续工作 ({len(forward)} 篇)\n")
        print(f"{'#':>3} | {'年份':>4} | {'引用':>6} | {'标题':<60} | 会议")
        print(f"{'---':>3}-+-{'----':>4}-+-{'------':>6}-+-{'-'*60}-+-{'---'}")
        for i, c in enumerate(forward, 1):
            t = c.get("title", "")
            if len(t) > 60:
                t = t[:57] + "..."
            year = c.get("year") or ""
            cites = c.get("citationCount") or 0
            print(f"{i:3d} | {year:>4} | {cites:6d} | "
                  f"{t:<60} | {c.get('venue', '')}")
    else:
        print("  (无引用数据)")

    # Step 3: Backward references
    print(f"\n获取参考文献 (top {top_n})...")
    backward = get_paper_references(s2_id, limit=top_n, api_key=s2_key, cache=cache)

    if backward:
        print(f"\n### 论文引用的参考文献 ({len(backward)} 篇)\n")
        print(f"{'#':>3} | {'年份':>4} | {'引用':>6} | {'标题':<60} | 会议")
        print(f"{'---':>3}-+-{'----':>4}-+-{'------':>6}-+-{'-'*60}-+-{'---'}")
        for i, r in enumerate(backward, 1):
            t = r.get("title", "")
            if len(t) > 60:
                t = t[:57] + "..."
            year = r.get("year") or ""
            cites = r.get("citationCount") or 0
            print(f"{i:3d} | {year:>4} | {cites:6d} | "
                  f"{t:<60} | {r.get('venue', '')}")
    else:
        print("  (无参考文献数据)")

    # Step 4: LLM influence analysis
    if forward and total_cites >= 5:
        print(f"\n分析引用影响力...")
        citing_text = "\n".join(
            f"- [{c.get('year', '')}] {c.get('title', '')} "
            f"(引用: {c.get('citationCount', 0)}, 会议: {c.get('venue', '')})"
            for c in forward[:top_n]
        )
        prompt = CITATION_IMPACT_PROMPT.format(
            title=title,
            abstract=abstract[:1000] if abstract else "(无摘要)",
            citation_count=total_cites,
            n=len(forward[:top_n]),
            citing_papers_text=citing_text,
        )

        result = call_scout_llm(api, prompt, timeout)
        result = _try_repair_result(result, api, timeout)

        if result and not result.get("parse_error"):
            print(f"\n### 影响力分析\n")
            reason = result.get("popularity_reason", "")
            if reason:
                print(f"**为什么被广泛引用**: {reason}\n")
            dirs = result.get("followup_directions", [])
            if dirs:
                print("**后续研究方向**:")
                for d in dirs:
                    print(f"  - {d}")
                print()
            trend = result.get("trend_impact", "")
            if trend:
                print(f"**趋势影响**: {trend}\n")
    elif total_cites < 5:
        print(f"\n(被引次数 < 5，跳过 LLM 影响力分析)")

    print()


def cmd_deploy(args):
    """Deploy reports to Hugo site."""
    reports_dir = get_reports_dir(args)
    hugo_site = get_hugo_site(args)

    if not hugo_site.exists():
        logger.error("Hugo 站点目录不存在: %s", hugo_site)
        sys.exit(1)

    if not reports_dir.exists():
        logger.error("报告目录不存在: %s", reports_dir)
        sys.exit(1)

    if args.date:
        try:
            target_date = date.fromisoformat(args.date)
        except ValueError:
            logger.error("日期格式无效: %s，请使用 YYYY-MM-DD", args.date)
            sys.exit(1)
        md_files = [reports_dir / f"{target_date.isoformat()}-research.md"]
        md_files = [f for f in md_files if f.exists()]
        if not md_files:
            logger.warning("未找到 %s 的研究报告", target_date.isoformat())
            sys.exit(0)
    else:
        md_files = sorted(reports_dir.glob("*-research.md"))
        if not md_files:
            logger.warning("报告目录中没有研究报告 .md 文件")
            sys.exit(0)

    hugo_content_dir = resolve_site_content_dir(hugo_site, "research")
    deployed: set[str] = set()
    if hugo_content_dir.exists():
        for p in hugo_content_dir.glob("*-research.md"):
            deployed.add(p.stem)

    force = getattr(args, "force", False)
    to_deploy = []
    skipped = 0
    for md_file in md_files:
        stem = md_file.stem
        if not force and stem in deployed:
            skipped += 1
            continue
        date_str = stem.replace("-research", "")
        try:
            file_date = date.fromisoformat(date_str)
        except ValueError:
            logger.warning("跳过无法解析日期的文件: %s", md_file.name)
            continue
        to_deploy.append((md_file, file_date))

    logger.info("报告总数: %d, 已部署: %d, 待部署: %d", len(md_files), skipped, len(to_deploy))

    if not to_deploy:
        logger.info("所有报告均已部署")
        sys.exit(0)

    api = getattr(args, "api", "ollama")
    for md_file, file_date in to_deploy:
        markdown_body = md_file.read_text(encoding="utf-8")
        generate_hugo_post(markdown_body, file_date, hugo_site, api=api,
                           force=force,
                           overwrite_human=getattr(args, "overwrite_human", False))

    run_hugo_update(hugo_site)


def cmd_config(args):
    """View or initialize config file."""
    if args.init:
        _config_init()
    else:
        _config_show()


def _config_show():
    """Display current config."""
    print(f"配置文件路径: {_SCOUT_CONFIG_PATH}")
    if _SCOUT_CONFIG_PATH.exists():
        cfg = load_scout_config()
        print("配置内容:")
        print(json.dumps(cfg, ensure_ascii=False, indent=2))
    else:
        print("(配置文件不存在，使用默认值)")

    print()
    print("当前生效路径:")
    from scout.config import REPORTS_DIR, CACHE_DIR, LOGS_DIR, DEFAULT_HUGO_SITE
    print(f"  projects_dir: {PROJECTS_DIR}")
    print(f"  reports_dir:  {REPORTS_DIR}")
    print(f"  cache_dir:    {CACHE_DIR}")
    print(f"  logs_dir:     {LOGS_DIR}")
    print(f"  hugo_site:    {DEFAULT_HUGO_SITE}")

    print()
    print("当前生效参数:")
    cfg = load_scout_config()
    print(f"  default_api:              {cfg.get('default_api', 'ollama')}")
    print(f"  default_language:         {cfg.get('default_language', DEFAULT_LANGUAGE)}")
    print(f"  default_lookback_days:    {cfg.get('default_lookback_days', DEFAULT_LOOKBACK_DAYS)}")
    print(f"  default_max_results:      {cfg.get('default_max_results', MAX_PAPERS_PER_PROJECT)}")
    print(f"  default_top_papers_in_report: {cfg.get('default_top_papers_in_report', TOP_PAPERS_IN_REPORT)}")
    print(f"  max_high_relevance:       {cfg.get('max_high_relevance', MAX_HIGH_RELEVANCE)}")
    s2k = cfg.get("semantic_scholar_api_key", "")
    print(f"  semantic_scholar_api_key: {'****' + s2k[-4:] if len(s2k) > 4 else '(未设置)' if not s2k else s2k}")


def _config_init():
    """Interactive config creation."""
    print(f"配置文件路径: {_SCOUT_CONFIG_PATH}")
    if _SCOUT_CONFIG_PATH.exists():
        overwrite = input("配置文件已存在，是否覆盖？[y/N] ").strip().lower()
        if overwrite != "y":
            print("取消")
            return

    cfg = {}

    api = input("默认 LLM 后端 [ollama/anthropic/openai/claude_cli] (默认 ollama): ").strip()
    if api in ("anthropic", "openai", "claude_cli", "ollama"):
        cfg["default_api"] = api
    else:
        cfg["default_api"] = "ollama"

    lang = input("LLM output language [zh/en/...] (default zh): ").strip()
    if lang:
        cfg["default_language"] = lang
    else:
        cfg["default_language"] = DEFAULT_LANGUAGE

    from scout.config import DEFAULT_HUGO_SITE
    hugo = input(f"Hugo 站点路径 (留空使用 {DEFAULT_HUGO_SITE}): ").strip()
    if hugo:
        cfg["hugo_site"] = hugo

    lookback = input("默认搜索回溯天数 (默认 7): ").strip()
    if lookback.isdigit():
        cfg["default_lookback_days"] = int(lookback)

    max_res = input("默认每次最多搜索论文数 (默认 50): ").strip()
    if max_res.isdigit():
        cfg["default_max_results"] = int(max_res)

    top_n = input("报告中展示的高分论文数 (默认 5): ").strip()
    if top_n.isdigit():
        cfg["default_top_papers_in_report"] = int(top_n)

    s2_key = input("Semantic Scholar API key (可选，留空跳过): ").strip()
    if s2_key:
        cfg["semantic_scholar_api_key"] = s2_key

    _SCOUT_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(_SCOUT_CONFIG_PATH, json.dumps(cfg, ensure_ascii=False, indent=2))
    print(f"\n[ok] 配置已保存: {_SCOUT_CONFIG_PATH}")
    print(json.dumps(cfg, ensure_ascii=False, indent=2))


# ─── CLI entry point ────────────────────────────────────────────────

def main():
    # Initialize logging
    setup_logging()

    parser = argparse.ArgumentParser(
        description="Research Paper Scout — 个人论文发现与管理系统")
    subparsers = parser.add_subparsers(dest="command")

    # ── init ──
    sp_init = subparsers.add_parser("init", help="创建新研究项目")
    sp_init.add_argument("name", type=str, help="项目 ID (小写字母、数字、连字符)")
    sp_init.add_argument("--title", type=str, default=None, help="项目标题")
    sp_init.add_argument("--keywords", type=str, nargs="+", default=None, help="搜索关键词")
    sp_init.add_argument("--categories", type=str, nargs="+", default=None, help="arXiv 分类")
    sp_init.add_argument("--questions", type=str, nargs="+", default=None, help="开放问题")
    sp_init.add_argument("--from-overview", type=str, default=None, help="从已有 overview.md 构建项目")
    sp_init.add_argument("--api", type=str, choices=["anthropic", "openai", "ollama", "claude_cli"], default=None)
    sp_init.add_argument("--timeout", type=int, default=None)

    # ── ask ──
    sp_ask = subparsers.add_parser("ask", help="自然语言搜索 (自动解析意图 → 搜索 → 评估)")
    sp_ask.add_argument("query", nargs="+", help="自然语言查询 (如 '找 Pieter Abbeel 最近的机器人操作论文')")
    sp_ask.add_argument("--api", type=str, choices=["anthropic", "openai", "ollama", "claude_cli"], default=None)
    sp_ask.add_argument("--timeout", type=int, default=None)
    sp_ask.add_argument("--language", type=str, default=None)
    sp_ask.add_argument("--no-cache", action="store_true")
    sp_ask.add_argument("--deploy", action="store_true", help="生成报告后部署到 Hugo")
    sp_ask.add_argument("--hugo-site", type=str, default=None)
    sp_ask.add_argument("--reports-dir", type=str, default=None)
    sp_ask.add_argument("--insight", action="store_true",
                        help="启用论文深度洞察分析")
    sp_ask.add_argument("--insight-top-n", type=int, default=None)

    # ── list ──
    sp_list = subparsers.add_parser("list", help="列出所有项目")
    sp_list.add_argument("--all", action="store_true", help="包含 ask 命令创建的临时项目")

    # ── search ──
    sp_search = subparsers.add_parser("search", help="搜索论文（不进行 LLM 评估）")
    sp_search.add_argument("--project", type=str, default=None)
    sp_search.add_argument("--lookback-days", type=int, default=None)
    sp_search.add_argument("--max-results", type=int, default=None)
    sp_search.add_argument("--conference", type=str, default=None)
    sp_search.add_argument("--author", type=str, default=None)
    sp_search.add_argument("--source", type=str, nargs="+", default=None)
    sp_search.add_argument("--no-cache", action="store_true")

    # ── report ──
    sp_report = subparsers.add_parser("report", help="完整管线")
    sp_report.add_argument("--project", type=str, default=None)
    sp_report.add_argument("--lookback-days", type=int, default=None)
    sp_report.add_argument("--max-results", type=int, default=None)
    sp_report.add_argument("--conference", type=str, default=None)
    sp_report.add_argument("--author", type=str, default=None)
    sp_report.add_argument("--source", type=str, nargs="+", default=None)
    sp_report.add_argument("--api", type=str, choices=["anthropic", "openai", "ollama", "claude_cli"], default=None)
    sp_report.add_argument("--timeout", type=int, default=None)
    sp_report.add_argument("--language", type=str, default=None)
    sp_report.add_argument("--no-cache", action="store_true")
    sp_report.add_argument("--deploy", action="store_true")
    sp_report.add_argument("--hugo-site", type=str, default=None)
    sp_report.add_argument("--reports-dir", type=str, default=None)
    sp_report.add_argument("--insight", action="store_true",
                           help="启用论文深度洞察 (Stage 4: 写作分析 + Stage 5: OpenReview 审稿意见)")
    sp_report.add_argument("--insight-top-n", type=int, default=None,
                           help="Insight 分析的论文数 (默认 3)")

    # ── profile ──
    sp_profile = subparsers.add_parser("profile", help="分析研究者")
    sp_profile.add_argument("names", nargs="*", default=[])
    sp_profile.add_argument("--from-file", type=str, default=None)
    sp_profile.add_argument("--mode", type=str, choices=["fast", "detailed"], default=None)
    sp_profile.add_argument("--depth", type=int, choices=[0, 1, 2, 3], default=None)
    sp_profile.add_argument("--max-students", type=int, default=None)
    sp_profile.add_argument("--model", type=str, choices=["sonnet", "opus", "haiku"], default=None)
    sp_profile.add_argument("--api", type=str, choices=["anthropic", "openai", "ollama", "claude_cli"], default=None)
    sp_profile.add_argument("--affiliation", type=str, default="")
    hint_group = sp_profile.add_mutually_exclusive_group()
    hint_group.add_argument("--paper", type=str, default="")
    hint_group.add_argument("--author-id", type=str, default="")
    sp_profile.add_argument("--homepage", type=str, default="")
    sp_profile.add_argument("--deploy", action="store_true")
    sp_profile.add_argument("--hugo-site", type=str, default=None)
    sp_profile.add_argument("--no-cache", action="store_true")

    # ── citations ──
    sp_citations = subparsers.add_parser("citations", help="引用图分析")
    sp_citations.add_argument("paper_id", type=str)
    sp_citations.add_argument("--top-n", type=int, default=10)
    sp_citations.add_argument("--api", type=str, choices=["anthropic", "openai", "ollama", "claude_cli"], default=None)
    sp_citations.add_argument("--timeout", type=int, default=None)
    sp_citations.add_argument("--no-cache", action="store_true")

    # ── deploy ──
    sp_deploy = subparsers.add_parser("deploy", help="部署报告到 Hugo 站点")
    sp_deploy.add_argument("--date", type=str, default=None)
    sp_deploy.add_argument("--force", action="store_true")
    sp_deploy.add_argument("--overwrite-human", action="store_true",
                           help="危险：允许覆盖无 gadget 标记的手写站点文件")
    sp_deploy.add_argument("--hugo-site", type=str, default=None)
    sp_deploy.add_argument("--reports-dir", type=str, default=None)

    # ── config ──
    sp_config = subparsers.add_parser("config", help="管理配置")
    sp_config.add_argument("--init", action="store_true")
    sp_config.add_argument("--show", action="store_true")

    args = parser.parse_args()

    if hasattr(args, "api") and args.api is None:
        cfg = load_scout_config()
        args.api = cfg.get("default_api", "ollama")

    if args.command == "init":
        cmd_init(args)
    elif args.command == "ask":
        cmd_ask(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "report":
        cmd_report(args)
    elif args.command == "profile":
        cmd_profile(args)
    elif args.command == "citations":
        cmd_citations(args)
    elif args.command == "deploy":
        cmd_deploy(args)
    elif args.command == "config":
        cmd_config(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
