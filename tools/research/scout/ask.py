"""Natural language 'ask' command: parse intent, route search, create project."""

from __future__ import annotations

import re
import logging
from datetime import date

from common.json_utils import try_repair_result as _try_repair_result

from scout.config import (
    DEFAULT_LOOKBACK_DAYS,
    MAX_PAPERS_PER_PROJECT,
    get_logger,
)
from scout.evaluate import call_scout_llm
from scout.prompts import ASK_INTENT_PROMPT
from scout.search import (
    paper_id as _paper_id,
    search_arxiv_conference,
    search_arxiv_author,
    search_source,
    load_search_cache,
    save_search_cache,
)

logger = get_logger()

# ─── Valid arXiv category prefixes ─────────────────────────────────

_VALID_CATEGORY_RE = re.compile(
    r"^(astro-ph|cond-mat|cs|econ|eess|gr-qc|hep-ex|hep-lat|hep-ph|hep-th|"
    r"math|math-ph|nlin|nucl-ex|nucl-th|physics|q-bio|q-fin|quant-ph|stat)"
    r"(\.[A-Za-z]+(-[A-Za-z]+)*)?$"
)

# ─── Schema validation (FEAT-006) ──────────────────────────────────

_VALID_SEARCH_MODES = {"topic", "author", "conference", "journal", "mixed"}
_VALID_SOURCES = {"arxiv", "biorxiv", "pubmed"}


def validate_ask_plan(plan: dict) -> dict:
    """Validate and sanitize the LLM-parsed ask plan.

    Returns a new dict with validated fields and sensible defaults.
    Raises ValueError if plan is fundamentally unusable (no keywords AND no author/conference).
    """
    if not isinstance(plan, dict) or plan.get("parse_error"):
        raise ValueError("LLM 解析失败，无法生成搜索计划")

    validated: dict = {}

    # title
    validated["title"] = str(plan.get("title", "")).strip() or "Untitled Ask Query"

    # search_mode
    mode = str(plan.get("search_mode", "topic")).lower().strip()
    validated["search_mode"] = mode if mode in _VALID_SEARCH_MODES else "topic"

    # search_keywords — must be a non-empty list for topic/mixed modes
    raw_kw = plan.get("search_keywords", [])
    if isinstance(raw_kw, str):
        raw_kw = [raw_kw]
    keywords = [str(k).strip() for k in raw_kw if str(k).strip()]
    validated["search_keywords"] = keywords

    # arxiv_categories — validate format
    raw_cats = plan.get("arxiv_categories", [])
    if isinstance(raw_cats, str):
        raw_cats = [raw_cats]
    categories = []
    for cat in raw_cats:
        cat = str(cat).strip()
        if _VALID_CATEGORY_RE.match(cat):
            categories.append(cat)
        else:
            logger.warning("忽略无效 arXiv 分类: %s", cat)
    validated["arxiv_categories"] = categories

    # sources — validate against known sources
    raw_sources = plan.get("sources", ["arxiv"])
    if isinstance(raw_sources, str):
        raw_sources = [raw_sources]
    sources = [s.strip().lower() for s in raw_sources if s.strip().lower() in _VALID_SOURCES]
    validated["sources"] = sources or ["arxiv"]

    # author (for author/mixed mode)
    validated["author"] = str(plan.get("author", "")).strip() or None

    # conference (for conference/mixed mode)
    validated["conference"] = str(plan.get("conference", "")).strip() or None

    # pubmed_journals
    raw_journals = plan.get("pubmed_journals", [])
    if isinstance(raw_journals, str):
        raw_journals = [raw_journals]
    validated["pubmed_journals"] = [str(j).strip() for j in raw_journals if str(j).strip()]

    # biorxiv_categories
    raw_bio = plan.get("biorxiv_categories", [])
    if isinstance(raw_bio, str):
        raw_bio = [raw_bio]
    validated["biorxiv_categories"] = [str(c).strip() for c in raw_bio if str(c).strip()]

    # lookback_days
    raw_lookback = plan.get("lookback_days")
    if isinstance(raw_lookback, (int, float)) and 1 <= raw_lookback <= 365:
        validated["lookback_days"] = int(raw_lookback)
    else:
        validated["lookback_days"] = 30  # intentionally wider than DEFAULT_LOOKBACK_DAYS (7) for ad-hoc queries

    # overview_summary — for populating overview.md
    validated["overview_summary"] = str(plan.get("overview_summary", "")).strip()

    # open_questions
    raw_questions = plan.get("open_questions", [])
    if isinstance(raw_questions, str):
        raw_questions = [raw_questions]
    validated["open_questions"] = [str(q).strip() for q in raw_questions if str(q).strip()]

    # Validate minimum viability
    mode = validated["search_mode"]
    has_keywords = bool(validated["search_keywords"])
    has_author = bool(validated["author"])
    has_conference = bool(validated["conference"])

    if mode == "author" and not has_author:
        if has_keywords:
            logger.warning("author 模式但未提取到作者名，回退到 topic 模式")
            validated["search_mode"] = "topic"
        else:
            raise ValueError("无法从输入中提取作者名或关键词")

    if mode == "conference" and not has_conference:
        if has_keywords:
            logger.warning("conference 模式但未提取到会议名，回退到 topic 模式")
            validated["search_mode"] = "topic"
        else:
            raise ValueError("无法从输入中提取会议名或关键词")

    if mode == "topic" and not has_keywords:
        raise ValueError("topic 模式但未提取到关键词")

    if mode == "journal" and not has_keywords:
        raise ValueError("journal 模式但未提取到关键词")

    if mode == "journal" and not validated["pubmed_journals"]:
        logger.warning("journal 模式但未提取到期刊名，搜索可能不够精确")

    if mode == "mixed" and not (has_keywords or has_author or has_conference):
        raise ValueError("mixed 模式但未提取到任何搜索条件")

    return validated


# ─── Intent parsing (FEAT-001) ─────────────────────────────────────

def parse_ask_intent(query: str, api: str = "claude_cli",
                     timeout: int = 600) -> dict:
    """Parse natural language query into a structured search plan via LLM.

    Returns a validated dict with search parameters.
    Raises ValueError if parsing fails or result is unusable.
    """
    prompt = ASK_INTENT_PROMPT.format(query=query)
    logger.info("解析自然语言查询 (api=%s)...", api)
    result = call_scout_llm(api, prompt, timeout)

    if not isinstance(result, dict):
        raise ValueError(f"LLM 返回了非字典类型: {type(result).__name__}")

    result = _try_repair_result(result, api, timeout)

    if result.get("parse_error"):
        raw_preview = str(result.get("raw_response", ""))[:200]
        raise ValueError(f"LLM JSON 解析失败: {raw_preview}")

    return validate_ask_plan(result)


# ─── Search routing (FEAT-002) ─────────────────────────────────────

def route_search(plan: dict, project: dict, no_cache: bool = False,
                 today: date | None = None) -> list[dict]:
    """Route search based on parsed plan, returning deduplicated paper list.

    Supports topic, author, conference, journal, and mixed modes.
    Mixed mode runs multiple searches and merges results by paper_id.
    """
    if today is None:
        today = date.today()

    mode = plan["search_mode"]
    lookback = plan.get("lookback_days", DEFAULT_LOOKBACK_DAYS)
    max_results = MAX_PAPERS_PER_PROJECT

    all_papers: list[dict] = []
    seen_ids: set[str] = set()

    def _add_papers(papers: list[dict]) -> None:
        for p in papers:
            pid = _paper_id(p)
            if pid and pid not in seen_ids:
                seen_ids.add(pid)
                all_papers.append(p)

    if mode == "author" or (mode == "mixed" and plan.get("author")):
        author = plan["author"]
        logger.info("搜索作者: %s", author)
        if not no_cache:
            cached = load_search_cache(project, today, author=author)
            if cached is not None:
                logger.info("作者搜索缓存命中: %d 篇", len(cached))
                _add_papers(cached)
            else:
                papers = search_arxiv_author(author, project, max_results,
                                             lookback_days=lookback)
                save_search_cache(project, today, papers, author=author)
                _add_papers(papers)
        else:
            papers = search_arxiv_author(author, project, max_results,
                                         lookback_days=lookback)
            _add_papers(papers)

    if mode == "conference" or (mode == "mixed" and plan.get("conference")):
        conference = plan["conference"]
        logger.info("搜索会议: %s", conference)
        # Don't pass project keywords to conference search — the conference
        # name alone is the primary filter; keywords make the query too complex
        # and trigger arXiv rate limits / empty results.
        if not no_cache:
            cached = load_search_cache(project, today, conference)
            if cached is not None:
                logger.info("会议搜索缓存命中: %d 篇", len(cached))
                _add_papers(cached)
            else:
                papers = search_arxiv_conference(conference, None, max_results)
                save_search_cache(project, today, papers, conference)
                _add_papers(papers)
        else:
            papers = search_arxiv_conference(conference, None, max_results)
            _add_papers(papers)

    if mode in ("topic", "journal", "mixed"):
        sources = plan.get("sources", ["arxiv"])
        # journal mode: force PubMed if not already included
        if mode == "journal" and "pubmed" not in sources:
            sources = list(sources) + ["pubmed"]

        for src in sources:
            logger.info("搜索数据源: %s", src)
            src_papers = search_source(project, src, lookback, max_results,
                                       no_cache, today)
            _add_papers(src_papers)

    if all_papers:
        project["last_searched"] = today.isoformat()

    logger.info("搜索完成: %d 篇论文 (去重后)", len(all_papers))
    return all_papers
