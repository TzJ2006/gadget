"""Stage 4+5: Paper insight analysis + OpenReview review consensus.

Pipeline extension for Research Scout:
  Stage 4: Full-text download → LLM insight analysis (writing + publishability + knowledge)
  Stage 5: OpenReview review fetch → LLM consensus analysis
  Synthesis: Cross-paper writing guide generation
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from common.cache import DiskCache
from common.io import atomic_write
from common.json_utils import parse_json_response as _parse_json_response

from research.scout.config import (
    CACHE_DIR,
    INSIGHT_CACHE_DIR,
    INSIGHT_TOP_N,
    MAX_FULLTEXT_CHARS,
    TOP_PAPERS_IN_REPORT,
    resolve_param,
    get_logger,
)
from research.scout.evaluate import call_scout_llm
from research.scout.prompts import (
    INSIGHT_ANALYSIS_PROMPT,
    INSIGHT_ABSTRACT_PROMPT,
    REVIEW_CONSENSUS_PROMPT,
    WRITING_GUIDE_PROMPT,
    language_instruction,
)
from research.scout.search import paper_id as _paper_id

logger = get_logger()


# ─── Full-text bridge ──────────────────────────────────────────────

def download_paper_fulltext(paper: dict, cache: DiskCache | None = None) -> str:
    """Download full text for a paper, with truncation.

    Uses lazy import of profiler's arxiv_client to avoid coupling.
    Returns truncated text (MAX_FULLTEXT_CHARS) or empty string on failure.
    """
    source = paper.get("source", "arxiv")
    arxiv_id = paper.get("arxiv_id", "") or paper.get("paper_id", "")

    if source == "arxiv" and arxiv_id:
        try:
            # Lazy import to avoid circular dependency (matches analyze_citations pattern)
            from research.apis.arxiv_client import download_fulltext
            pdf_url = paper.get("pdf_url", "")
            text = download_fulltext(arxiv_id, pdf_url=pdf_url, cache=cache)
            if text:
                return text[:MAX_FULLTEXT_CHARS]
        except ImportError:
            logger.warning("arxiv_client 不可用，跳过全文下载")
        except Exception as e:
            logger.warning("全文下载失败 %s: %s", arxiv_id, e)
    elif source == "biorxiv":
        doi = paper.get("doi", "") or paper.get("paper_id", "").replace("biorxiv:", "")
        if doi:
            text = _download_biorxiv_fulltext(doi, cache)
            if text:
                return text[:MAX_FULLTEXT_CHARS]

    # PubMed and other sources: degrade to abstract
    return ""


def _download_biorxiv_fulltext(doi: str, cache: DiskCache | None = None) -> str:
    """Best-effort bioRxiv full-text download via HTML."""
    import urllib.request

    cache_key = f"fulltext:biorxiv:{doi}"
    if cache:
        cached = cache.get("api/pdfs", cache_key)
        if cached is not None:
            return cached

    url = f"https://www.biorxiv.org/content/{doi}.full"
    try:
        from research.apis.rate_limiter import web_limiter
        web_limiter.acquire()
        req = urllib.request.Request(url, headers={
            "User-Agent": "research-tool/1.0 (academic research)",
        })
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status != 200:
                return ""
            html = resp.read().decode("utf-8", errors="replace")

        # Simple text extraction: strip HTML tags
        import re
        text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        if cache and len(text) > 500:
            cache.put("api/pdfs", cache_key, text)
        return text if len(text) > 500 else ""
    except Exception as e:
        logger.debug("bioRxiv 全文下载失败 %s: %s", doi, e)
        return ""


# ─── Insight cache ─────────────────────────────────────────────────

def _insight_cache_key(
    paper_id: str,
    content_hash: str,
    language: str = "en",
    api: str = "claude_cli",
) -> str:
    """Cache key for insight analysis: paper_id + content hash + language + api."""
    raw = json.dumps(
        {
            "paper_id": paper_id,
            "content_hash": content_hash,
            "language": language,
            "api": api,
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _content_hash(text: str) -> str:
    """SHA-256 hash of content for cache keying."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _load_insight_cache(cache_key: str) -> dict | None:
    """Load cached insight analysis."""
    cache_path = INSIGHT_CACHE_DIR / f"{cache_key}.json"
    if not cache_path.exists():
        return None
    try:
        return json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _save_insight_cache(cache_key: str, data: dict) -> None:
    """Save insight analysis to cache."""
    INSIGHT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = INSIGHT_CACHE_DIR / f"{cache_key}.json"
    atomic_write(cache_path, json.dumps(data, ensure_ascii=False, indent=2))


# ─── Stage 4: Insight analysis ─────────────────────────────────────

def analyze_paper_insight(
    paper: dict,
    fulltext: str,
    *,
    api: str = "claude_cli",
    timeout: int = 600,
    language: str = "en",
) -> dict:
    """Analyze a single paper for writing structure, publishability, and knowledge.

    Returns dict with writing_structure, publishability, knowledge_extraction fields.
    Uses INSIGHT_ANALYSIS_PROMPT for full text, INSIGHT_ABSTRACT_PROMPT for abstract-only.
    """
    title = paper.get("title", "")
    abstract = paper.get("abstract", "")

    if fulltext and len(fulltext) > 500:
        prompt = INSIGHT_ANALYSIS_PROMPT.format(
            title=title,
            abstract=abstract,
            fulltext=fulltext,
            language_instruction=language_instruction(language),
        )
    else:
        # Abstract-only reduced analysis
        prompt = INSIGHT_ABSTRACT_PROMPT.format(
            title=title,
            abstract=abstract,
            language_instruction=language_instruction(language),
        )

    result = call_scout_llm(api, prompt, timeout)
    if result.get("parse_error"):
        logger.warning("Insight 分析 JSON 解析失败: %s", _paper_id(paper))
        return {}

    return result


# ─── Stage 5: Review consensus ─────────────────────────────────────

def analyze_review_consensus(
    paper: dict,
    reviews: list[dict],
    *,
    api: str = "claude_cli",
    timeout: int = 600,
    language: str = "en",
) -> dict:
    """Analyze reviewer consensus from OpenReview reviews.

    Behavior by reviewer count:
      0 reviews → returns empty dict (skip)
      1 review  → single reviewer summary (no consensus)
      2 reviews → limited consensus (notes small sample)
      3+ reviews → full consensus analysis
    """
    if not reviews:
        return {}

    title = paper.get("title", "")
    review_count = len(reviews)

    reviews_text = _format_reviews(reviews)

    if review_count == 1:
        mode = "single"
    elif review_count == 2:
        mode = "limited"
    else:
        mode = "full"

    prompt = REVIEW_CONSENSUS_PROMPT.format(
        title=title,
        review_count=review_count,
        mode=mode,
        reviews_text=reviews_text,
        language_instruction=language_instruction(language),
    )

    result = call_scout_llm(api, prompt, timeout)
    if result.get("parse_error"):
        logger.warning("Review consensus 分析失败: %s", _paper_id(paper))
        return {}

    result["review_count"] = review_count
    result["mode"] = mode
    return result


def _format_reviews(reviews: list[dict]) -> str:
    """Format OpenReview reviews for LLM prompt."""
    parts = []
    for i, r in enumerate(reviews, 1):
        lines = [f"### Reviewer {i}"]
        rating = r.get("rating", "")
        if rating:
            lines.append(f"- Rating: {rating}")
        confidence = r.get("confidence", "")
        if confidence:
            lines.append(f"- Confidence: {confidence}")
        for field in ("soundness", "presentation", "contribution"):
            val = r.get(field, "")
            if val:
                lines.append(f"- {field.capitalize()}: {val}")
        for field in ("strengths", "weaknesses", "questions", "suggestions"):
            val = r.get(field, "")
            if val:
                lines.append(f"\n**{field.capitalize()}**:\n{val}")
        summary = r.get("summary", "")
        if summary:
            lines.append(f"\n**Summary**: {summary}")
        parts.append("\n".join(lines))
    return "\n\n---\n\n".join(parts)


# ─── Writing guide synthesis ────────────────────────────────────────

def synthesize_writing_guide(
    papers_with_insights: list[dict],
    project: dict,
    *,
    api: str = "claude_cli",
    timeout: int = 600,
    language: str = "en",
) -> dict:
    """Synthesize cross-paper writing guide from all insight + review analyses.

    Returns dict with: writing_norms, review_focus, methodology_takeaways, code_references.
    """
    if not papers_with_insights:
        return {}

    papers_text = _format_papers_for_guide(papers_with_insights)

    prompt = WRITING_GUIDE_PROMPT.format(
        project_title=project.get("title", ""),
        project_keywords=", ".join(project.get("search_keywords", [])),
        papers_text=papers_text,
        language_instruction=language_instruction(language),
    )

    result = call_scout_llm(api, prompt, timeout)
    if result.get("parse_error"):
        logger.warning("Writing guide 综合失败")
        return {}

    return result


def _format_papers_for_guide(papers: list[dict]) -> str:
    """Format papers with their insight/review analyses for guide synthesis."""
    parts = []
    for p in papers:
        lines = [f"## {p.get('title', '')}"]
        lines.append(f"Venue: {p.get('venue', 'N/A')}")
        lines.append(f"Composite Score: {p.get('composite_score', 0):.1f}")

        ia = p.get("insight_analysis", {})
        if ia:
            ws = ia.get("writing_structure", {})
            if ws:
                lines.append(f"\n### Writing Structure")
                for k, v in ws.items():
                    lines.append(f"- {k}: {v}")
            pub = ia.get("publishability", {})
            if pub:
                lines.append(f"\n### Publishability")
                for k, v in pub.items():
                    if isinstance(v, list):
                        lines.append(f"- {k}: {'; '.join(str(x) for x in v)}")
                    else:
                        lines.append(f"- {k}: {v}")
            ke = ia.get("knowledge_extraction", {})
            if ke:
                lines.append(f"\n### Knowledge")
                for k, v in ke.items():
                    if isinstance(v, list):
                        lines.append(f"- {k}: {'; '.join(str(x) for x in v)}")
                    else:
                        lines.append(f"- {k}: {v}")

        ra = p.get("review_analysis", {})
        if ra:
            lines.append(f"\n### Reviewer Feedback (n={ra.get('review_count', 0)})")
            avg = ra.get("average_rating", "")
            if avg:
                lines.append(f"- Average rating: {avg}")
            for field in ("consensus_strengths", "consensus_weaknesses", "controversies"):
                val = ra.get(field, "")
                if val:
                    if isinstance(val, list):
                        lines.append(f"- {field}: {'; '.join(str(x) for x in val)}")
                    else:
                        lines.append(f"- {field}: {val}")

        parts.append("\n".join(lines))
    return "\n\n---\n\n".join(parts)


# ─── Main pipeline entry point ─────────────────────────────────────

def run_insight_analysis(
    papers: list[dict],
    project: dict,
    *,
    api: str = "claude_cli",
    timeout: int = 600,
    language: str = "en",
    top_n: int | None = None,
    use_cache: bool = True,
) -> tuple[list[dict], dict]:
    """Run full insight pipeline on top papers.

    Args:
        papers: High-relevance papers sorted by composite_score (descending).
        project: Project dict.
        api: LLM backend.
        timeout: LLM call timeout.
        language: Output language.
        top_n: Number of papers to analyze (default: INSIGHT_TOP_N).
        use_cache: Whether to use cached results.

    Returns:
        (papers_with_insights, writing_guide) — papers list with insight_analysis
        and review_analysis attached, plus the synthesized writing guide dict.
    """
    if top_n is None:
        top_n = resolve_param(None, project, "insight_top_n", INSIGHT_TOP_N)

    # Cap to top_papers_in_report
    report_top = resolve_param(None, project, "top_papers_in_report", TOP_PAPERS_IN_REPORT)
    top_n = min(top_n, report_top, len(papers))

    if top_n <= 0:
        return [], {}

    target_papers = papers[:top_n]
    logger.info("Stage 4: Insight 分析 (%d 篇论文)...", len(target_papers))

    # Set up caches
    fulltext_cache = DiskCache(CACHE_DIR)

    # OpenReview client (lazy, may fail)
    or_client = _get_openreview_client()

    for i, paper in enumerate(target_papers):
        pid = _paper_id(paper)
        logger.info("  [%d/%d] %s", i + 1, len(target_papers), pid)

        # Stage 4a: Download full text FIRST — analysis depth (full-text vs
        # abstract-only) depends on it, so it must be part of the cache key.
        # Otherwise an abstract-only result cached on a first run (PDF/network
        # unavailable) is reused forever and never upgrades once full text
        # becomes available. download_paper_fulltext is itself cached.
        fulltext = download_paper_fulltext(paper, cache=fulltext_cache)
        if fulltext:
            logger.info("    全文: %d chars", len(fulltext))
        else:
            logger.info("    仅 abstract (全文不可用)")

        # Check insight cache (keyed by abstract + full-text content)
        content_hash = _content_hash(paper.get("abstract", "") + "\x00" + (fulltext or ""))
        cache_key = _insight_cache_key(pid, content_hash, language=language, api=api)
        if use_cache:
            cached = _load_insight_cache(cache_key)
            if cached:
                paper["insight_analysis"] = cached.get("insight_analysis", {})
                paper["review_analysis"] = cached.get("review_analysis", {})
                logger.info("    Insight 缓存命中")
                continue

        # Stage 4b: LLM insight analysis
        insight = analyze_paper_insight(
            paper, fulltext, api=api, timeout=timeout, language=language,
        )
        paper["insight_analysis"] = insight

        # Stage 5: OpenReview reviews
        review_analysis = {}
        if or_client:
            try:
                reviews_data = or_client.fetch_paper_reviews(paper)
                if reviews_data:
                    reviews = reviews_data.get("reviews", [])
                    if reviews:
                        logger.info("    OpenReview: %d reviews found", len(reviews))
                        review_analysis = analyze_review_consensus(
                            paper, reviews, api=api, timeout=timeout, language=language,
                        )
                    else:
                        logger.info("    OpenReview: 无审稿意见")
                else:
                    logger.info("    OpenReview: 未匹配到论文")
            except Exception as e:
                logger.warning("    OpenReview 失败: %s", e)
        paper["review_analysis"] = review_analysis

        # Cache result — only when Stage-4 insight succeeded; never pin {} permanently
        if use_cache and insight:
            _save_insight_cache(cache_key, {
                "insight_analysis": insight,
                "review_analysis": review_analysis,
            })

    # Synthesis: Writing guide
    papers_with_insights = [p for p in target_papers
                           if p.get("insight_analysis") or p.get("review_analysis")]
    writing_guide = {}
    if papers_with_insights:
        logger.info("生成研究写作指南 (基于 %d 篇论文)...", len(papers_with_insights))
        writing_guide = synthesize_writing_guide(
            papers_with_insights, project, api=api, timeout=timeout, language=language,
        )

    return target_papers, writing_guide


def _get_openreview_client():
    """Lazily create OpenReview client. Returns None if unavailable."""
    try:
        from research.apis.openreview_client import OpenReviewClient
        return OpenReviewClient()
    except ImportError:
        logger.info("openreview-py 未安装，跳过审稿意见获取")
        return None
    except Exception as e:
        logger.warning("OpenReview 客户端初始化失败: %s", e)
        return None
