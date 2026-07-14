"""Three-stage paper evaluation pipeline: screening -> deep analysis -> citation impact."""

from __future__ import annotations

import hashlib
import json
import logging

from common.io import atomic_write
from common.json_utils import (
    parse_json_response as _parse_json_response,
    try_repair_result as _try_repair_result,
)
from common.llm import call_llm_raw

from scout.config import (
    EVAL_CACHE_DIR,
    MAX_HIGH_RELEVANCE,
    TOP_PAPERS_IN_REPORT,
    DEFAULT_LANGUAGE,
    load_scout_config,
    resolve_param,
    get_logger,
)
from scout.prompts import (
    SCREENING_PROMPT,
    DEEP_EVAL_PROMPT,
    DIRECTION_SUGGESTION_PROMPT,
    language_instruction,
)
from scout.search import paper_id as _paper_id

logger = get_logger()

_VERSION_SUFFIX_RE = __import__("re").compile(r"v\d+$")


def _lookup_by_id(mapping: dict, pid: str) -> dict:
    """Lookup paper in mapping with fallback: strip version suffix if exact match fails."""
    if pid in mapping:
        return mapping[pid]
    stripped = _VERSION_SUFFIX_RE.sub("", pid)
    return mapping.get(stripped, {})


# ─── LLM backend ────────────────────────────────────────────────────

def _as_num(x) -> float:
    """Coerce a possibly-stringified score to float; fall back to 0 on failure."""
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0


def call_scout_llm(api: str, prompt: str, timeout: int = 600) -> dict:
    """Call LLM and return parsed JSON dict (uses common/ unified backend)."""
    try:
        raw = call_llm_raw(prompt, backend=api, model="sonnet", timeout=timeout)
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        return {"parse_error": True, "raw_response": str(e)}
    parsed = _parse_json_response(raw)
    if not isinstance(parsed, dict):
        # Top-level arrays / scalars would crash downstream .get() calls.
        return {"parse_error": True, "raw_response": repr(parsed)}
    return parsed


# ─── Eval cache ─────────────────────────────────────────────────────

def _screening_cache_key(project: dict, papers: list[dict],
                         language: str = DEFAULT_LANGUAGE,
                         api: str = "claude_cli") -> str:
    """Stage 1 screening cache key: project context + paper IDs + abstracts[:200]."""
    content = json.dumps({
        "stage": "screening",
        "project_id": project["id"],
        "keywords": project.get("search_keywords", []),
        "open_questions": project.get("open_questions", []),
        "language": language,
        "api": api,
        "paper_ids": [_paper_id(p) for p in papers],
        "paper_abstracts": [p["abstract"][:200] for p in papers],
    }, sort_keys=True)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _deep_eval_cache_key(project: dict, papers: list[dict],
                         language: str = DEFAULT_LANGUAGE,
                         api: str = "claude_cli",
                         current_methods: str = "") -> str:
    """Stage 2 deep evaluation cache key."""
    content = json.dumps({
        "stage": "deep_eval",
        "project_id": project["id"],
        "keywords": project.get("search_keywords", []),
        "open_questions": project.get("open_questions", []),
        "language": language,
        "api": api,
        "current_methods": current_methods,
        "paper_ids": [_paper_id(p) for p in papers],
        "paper_abstracts": [p["abstract"][:500] for p in papers],
    }, sort_keys=True)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _load_eval_cache(cache_key: str) -> dict | None:
    """Try to load evaluation cache."""
    cache_path = EVAL_CACHE_DIR / f"{cache_key}.json"
    if not cache_path.exists():
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("Cache corrupted, skipping: %s (%s)", cache_path.name, e)
        return None


def _save_eval_cache(cache_key: str, data: dict) -> None:
    """Save evaluation cache."""
    EVAL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = EVAL_CACHE_DIR / f"{cache_key}.json"
    atomic_write(cache_path, json.dumps(data, ensure_ascii=False, indent=2))


def _screening_is_usable(screened_papers: list[dict]) -> bool:
    """Quality gate: don't cache screening if every paper defaulted to low
    relevance with empty motivation/innovation (the LLM-failure signature)."""
    if not screened_papers:
        return False
    for p in screened_papers:
        if p.get("screening_relevance") == "high":
            return True
        if p.get("motivation") or p.get("innovation_point"):
            return True
    return False


def _deep_eval_is_usable(evaluated_papers: list[dict]) -> bool:
    """Quality gate: don't cache deep evaluation if every composite_score is 0
    (the LLM-failure signature)."""
    if not evaluated_papers:
        return False
    return any(e.get("composite_score", 0) for e in evaluated_papers)


# ─── Paper formatting ───────────────────────────────────────────────

def _format_papers_for_screening(papers: list[dict]) -> str:
    """Format paper list for Stage 1 quick screening (lightweight)."""
    parts = []
    for i, p in enumerate(papers, 1):
        first_author = p["authors"][0] if p.get("authors") else "unknown"
        venue = p.get("venue", "")
        venue_str = f"\nVenue: {venue}" if venue else ""
        pid = _paper_id(p)
        parts.append(
            f"### Paper {i}: [{pid}] {p['title']}\n"
            f"First Author: {first_author}\n"
            f"Categories: {', '.join(p.get('categories', []))}"
            f"{venue_str}\n"
            f"Abstract: {p['abstract'][:1000]}\n"
        )
    return "\n".join(parts)


def _format_papers_for_deep_eval(papers: list[dict]) -> str:
    """Format paper list for Stage 2 deep evaluation (full)."""
    parts = []
    for i, p in enumerate(papers, 1):
        authors_str = ", ".join(p["authors"][:5])
        if len(p["authors"]) > 5:
            authors_str += " et al."
        venue = p.get("venue", "")
        venue_str = f"\nVenue: {venue}" if venue else ""
        pid = _paper_id(p)
        parts.append(
            f"### Paper {i}: [{pid}] {p['title']}\n"
            f"Authors: {authors_str}\n"
            f"Published: {p['published']}\n"
            f"Categories: {', '.join(p.get('categories', []))}"
            f"{venue_str}\n"
            f"Abstract: {p['abstract']}\n"
        )
    return "\n".join(parts)


# ─── Three-stage evaluation ─────────────────────────────────────────

def _screen_papers(project: dict, papers: list[dict],
                   api: str = "claude_cli",
                   timeout: int = 600,
                   language: str = DEFAULT_LANGUAGE) -> list[dict]:
    """Stage 1: Quick screening of all papers."""
    if not papers:
        return []

    papers_text = _format_papers_for_screening(papers)
    prompt_overhead = 2000

    if len(papers_text) + prompt_overhead > 150000:
        return _screen_papers_chunked(project, papers, api, timeout, language)

    prompt = SCREENING_PROMPT.format(
        title=project["title"],
        keywords=", ".join(project.get("search_keywords", [])),
        open_questions="\n".join(f"- {q}" for q in project.get("open_questions", [])) or "(none)",
        papers_text=papers_text,
        language_instruction=language_instruction(language),
    )

    logger.info("Stage 1: 筛选 %d 篇论文...", len(papers))
    result = call_scout_llm(api, prompt, timeout)
    result = _try_repair_result(result, api, timeout)

    screenings = result.get("screenings", [])
    screen_by_id = {}
    for s in screenings:
        key = s.get("paper_id") or s.get("arxiv_id")
        if key:
            screen_by_id[key] = s

    for p in papers:
        sc = _lookup_by_id(screen_by_id, _paper_id(p))
        p["screening_relevance"] = sc.get("screening_relevance", "low")
        p["paper_type"] = sc.get("paper_type", "other")
        p["motivation"] = sc.get("motivation", "")
        p["innovation_point"] = sc.get("innovation_point", "")
        p["first_author"] = sc.get("first_author", p["authors"][0] if p.get("authors") else "unknown")
        p["institution"] = sc.get("institution", "unknown")

    missing = sum(1 for p in papers if not p.get("motivation") and not p.get("innovation_point"))
    if missing:
        logger.warning("Stage 1: %d/%d papers have empty motivation/innovation_point", missing, len(papers))
        for p in papers:
            if not p.get("motivation") and not p.get("innovation_point"):
                logger.debug("  Empty screening: %s", _paper_id(p))

    return papers


def _screen_papers_chunked(project: dict, papers: list[dict],
                           api: str, timeout: int,
                           language: str = DEFAULT_LANGUAGE) -> list[dict]:
    """Chunked screening for when total text exceeds 150K characters."""
    chunk_size = 25
    all_screened = []

    for i in range(0, len(papers), chunk_size):
        chunk = papers[i:i + chunk_size]
        chunk_num = i // chunk_size + 1
        total_chunks = (len(papers) + chunk_size - 1) // chunk_size
        logger.info("Stage 1 筛选第 %d/%d 批 (%d 篇)...", chunk_num, total_chunks, len(chunk))

        papers_text = _format_papers_for_screening(chunk)
        prompt = SCREENING_PROMPT.format(
            title=project["title"],
            keywords=", ".join(project.get("search_keywords", [])),
            open_questions="\n".join(f"- {q}" for q in project.get("open_questions", [])) or "(none)",
            papers_text=papers_text,
            language_instruction=language_instruction(language),
        )

        result = call_scout_llm(api, prompt, timeout)
        result = _try_repair_result(result, api, timeout)

        screenings = result.get("screenings", [])
        screen_by_id = {}
        for s in screenings:
            key = s.get("paper_id") or s.get("arxiv_id")
            if key:
                screen_by_id[key] = s

        for p in chunk:
            sc = _lookup_by_id(screen_by_id, _paper_id(p))
            p["screening_relevance"] = sc.get("screening_relevance", "low")
            p["paper_type"] = sc.get("paper_type", "other")
            p["motivation"] = sc.get("motivation", "")
            p["innovation_point"] = sc.get("innovation_point", "")
            p["first_author"] = sc.get("first_author", p["authors"][0] if p.get("authors") else "unknown")
            p["institution"] = sc.get("institution", "unknown")
            all_screened.append(p)

    missing = sum(1 for p in all_screened if not p.get("motivation") and not p.get("innovation_point"))
    if missing:
        logger.warning("Stage 1 (chunked): %d/%d papers have empty motivation/innovation_point", missing, len(all_screened))
        for p in all_screened:
            if not p.get("motivation") and not p.get("innovation_point"):
                logger.debug("  Empty screening: %s", _paper_id(p))

    return all_screened


def _deep_evaluate_papers(project: dict, papers: list[dict],
                          api: str = "claude_cli",
                          timeout: int = 600,
                          language: str = DEFAULT_LANGUAGE) -> list[dict]:
    """Stage 2: Deep analysis of high-relevance papers."""
    if not papers:
        return []

    from scout.project import extract_current_methods
    current_methods = extract_current_methods(project["id"])
    papers_text = _format_papers_for_deep_eval(papers)

    prompt = DEEP_EVAL_PROMPT.format(
        title=project["title"],
        keywords=", ".join(project.get("search_keywords", [])),
        open_questions="\n".join(f"- {q}" for q in project.get("open_questions", [])) or "(none)",
        current_methods=current_methods,
        papers_text=papers_text,
        language_instruction=language_instruction(language),
    )

    logger.info("Stage 2: 深度分析 %d 篇高相关性论文...", len(papers))
    result = call_scout_llm(api, prompt, timeout)
    result = _try_repair_result(result, api, timeout)

    evaluations = result.get("evaluations", [])
    eval_by_id = {}
    for e in evaluations:
        key = e.get("paper_id") or e.get("arxiv_id")
        if key:
            eval_by_id[key] = e

    merged = []
    for p in papers:
        ev = _lookup_by_id(eval_by_id, _paper_id(p))
        entry = {**p, **ev}
        r = _as_num(ev.get("relevance", 0))
        n = _as_num(ev.get("novelty", 0))
        ins = _as_num(ev.get("inspiration", 0))
        entry["composite_score"] = round(0.4 * r + 0.3 * ins + 0.3 * n, 2)
        merged.append(entry)

    zero = sum(1 for e in merged if e.get("composite_score", 0) == 0)
    if zero:
        logger.warning("Stage 2: %d/%d papers have composite_score=0", zero, len(merged))

    merged.sort(key=lambda x: (x.get("composite_score", 0),
                                x.get("citation_count", 0) or 0), reverse=True)
    return merged


def analyze_citations(paper: dict, api: str = "claude_cli",
                      timeout: int = 600,
                      cache_obj=None, api_key: str = "") -> dict:
    """Stage 3: Citation impact analysis."""
    from research.apis.semantic_scholar import (
        get_paper_by_id, get_paper_citations, get_paper_references,
    )
    from research.prompts import CITATION_IMPACT_PROMPT

    pid = _paper_id(paper)
    if not pid:
        return {}

    s2_paper = get_paper_by_id(pid, api_key=api_key, cache=cache_obj)
    if not s2_paper:
        logger.warning("引用分析: 无法在 S2 找到论文 %s", pid)
        return {}

    s2_id = s2_paper["paperId"]
    total_citations = s2_paper.get("citationCount") or 0

    forward = get_paper_citations(s2_id, limit=20, api_key=api_key, cache=cache_obj)
    backward = get_paper_references(s2_id, limit=20, api_key=api_key, cache=cache_obj)

    top_citing = []
    for c in forward[:10]:
        top_citing.append({
            "title": c.get("title", ""),
            "year": c.get("year", 0),
            "citation_count": c.get("citationCount") or 0,
            "venue": c.get("venue", ""),
        })

    top_refs = []
    for r in backward[:10]:
        top_refs.append({
            "title": r.get("title", ""),
            "year": r.get("year", 0),
            "citation_count": r.get("citationCount") or 0,
            "venue": r.get("venue", ""),
        })

    influence_analysis = {}
    if forward and total_citations >= 5:
        citing_text = "\n".join(
            f"- [{c['year']}] {c['title']} (引用: {c['citation_count']}, 会议: {c['venue']})"
            for c in top_citing
        )
        prompt = CITATION_IMPACT_PROMPT.format(
            title=paper.get("title", ""),
            abstract=paper.get("abstract", "")[:1000],
            citation_count=total_citations,
            n=len(top_citing),
            citing_papers_text=citing_text,
        )
        influence_analysis = call_scout_llm(api, prompt, timeout)
        influence_analysis = _try_repair_result(influence_analysis, api, timeout)

    total_references = s2_paper.get("referenceCount")
    if total_references is None:
        total_references = len(backward)

    return {
        "total_forward_citations": total_citations,
        "total_references": total_references,
        "top_citing_papers": top_citing,
        "top_references": top_refs,
        "influence_analysis": influence_analysis,
    }


def evaluate_papers_for_project(project: dict, papers: list[dict],
                                api: str = "claude_cli",
                                timeout: int = 600,
                                use_cache: bool = True,
                                language: str = DEFAULT_LANGUAGE) -> dict:
    """Three-stage paper evaluation pipeline.

    Returns:
        {
            "high_relevance": [...],
            "low_relevance": [...],
            "screening_stats": {"total": N, "high_count": N, "low_count": N}
        }
    """
    if not papers:
        return {
            "high_relevance": [],
            "low_relevance": [],
            "screening_stats": {"total": 0, "high_count": 0, "low_count": 0},
        }

    # Stage 1: Quick screening
    screening_key = _screening_cache_key(project, papers, language, api)
    screened_papers = None

    if use_cache:
        cached = _load_eval_cache(f"screening_{screening_key}")
        if cached and "papers" in cached:
            logger.info("Stage 1 筛选缓存命中 (%d 篇)", len(cached["papers"]))
            screened_papers = cached["papers"]

    if screened_papers is None:
        screened_papers = _screen_papers(project, papers, api, timeout, language)
        if _screening_is_usable(screened_papers):
            _save_eval_cache(f"screening_{screening_key}", {"papers": screened_papers})
        else:
            logger.warning("筛选结果疑似 LLM 失败 (全部 low + 空 motivation/innovation)，跳过缓存")

    high_papers = [p for p in screened_papers if p.get("screening_relevance") == "high"]
    low_papers = [p for p in screened_papers if p.get("screening_relevance") != "high"]

    # Cap high-relevance count; overflow papers are demoted into low_papers so
    # they still appear in 文献阅读记录 instead of vanishing.
    max_high = resolve_param(None, project, "max_high_relevance", MAX_HIGH_RELEVANCE)
    if len(high_papers) > max_high:
        logger.warning("高相关性论文 (%d) 超过上限 %d，截断", len(high_papers), max_high)
        overflow = high_papers[max_high:]
        high_papers = high_papers[:max_high]
        low_papers = low_papers + overflow

    stats = {
        "total": len(screened_papers),
        "high_count": len(high_papers),
        "low_count": len(low_papers),
    }
    logger.info("筛选结果: %d 篇总计, %d 篇高相关, %d 篇低相关",
                stats["total"], stats["high_count"], stats["low_count"])

    # Stage 2: Deep analysis
    current_methods = ""
    if high_papers:
        from scout.project import extract_current_methods
        current_methods = extract_current_methods(project["id"])
    deep_key = _deep_eval_cache_key(project, high_papers, language, api, current_methods)
    evaluated_papers = None

    if use_cache and high_papers:
        cached = _load_eval_cache(f"deep_{deep_key}")
        if cached and "evaluations" in cached:
            logger.info("Stage 2 深度评估缓存命中 (%d 篇)", len(cached["evaluations"]))
            evaluated_papers = cached["evaluations"]

    if evaluated_papers is None and high_papers:
        evaluated_papers = _deep_evaluate_papers(project, high_papers, api, timeout, language)
        if _deep_eval_is_usable(evaluated_papers):
            _save_eval_cache(f"deep_{deep_key}", {"evaluations": evaluated_papers})
        else:
            logger.warning("深度评估结果疑似 LLM 失败 (composite_score 全为 0)，跳过缓存")

    if evaluated_papers is None:
        evaluated_papers = []

    return {
        "high_relevance": evaluated_papers,
        "low_relevance": low_papers,
        "screening_stats": stats,
    }


def suggest_directions(project: dict, top_papers: list[dict],
                       api: str = "claude_cli",
                       timeout: int = 600,
                       language: str = DEFAULT_LANGUAGE) -> list[dict]:
    """Generate research direction suggestions based on high-scoring papers."""
    if not top_papers:
        return []

    top_n = resolve_param(None, None, "top_papers_in_report", TOP_PAPERS_IN_REPORT)
    papers_text = []
    for p in top_papers[:top_n]:
        summary = p.get("two_sentence_summary", p.get("abstract", "")[:300])
        highlights = p.get("highlights", [])
        highlight_str = ""
        if highlights and isinstance(highlights, list) and len(highlights) > 0:
            h = highlights[0]
            if isinstance(h, dict):
                point = h.get("point", "")
                value = h.get("value_to_us", "")
                if point:
                    highlight_str = f"\n  Key highlight: {point}"
                if value:
                    highlight_str += f"\n  Value to us: {value}"

        pid = _paper_id(p)
        papers_text.append(
            f"- [{pid}] {p['title']} "
            f"(score: {p.get('composite_score', 0):.1f})\n"
            f"  {summary}{highlight_str}"
        )

    prompt = DIRECTION_SUGGESTION_PROMPT.format(
        title=project["title"],
        keywords=", ".join(project.get("search_keywords", [])),
        open_questions="\n".join(f"- {q}" for q in project.get("open_questions", [])) or "(无)",
        top_papers_text="\n".join(papers_text),
        language_instruction=language_instruction(language),
    )

    result = call_scout_llm(api, prompt, timeout)
    result = _try_repair_result(result, api, timeout)
    return result.get("directions", [])
