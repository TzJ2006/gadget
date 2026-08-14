"""Semantic Scholar API client for author metrics and co-authorship data."""

from __future__ import annotations

import logging
import math
import re
import urllib.request
import urllib.parse
import json
import time
from collections.abc import Iterable
from typing import Any

from research.apis.rate_limiter import s2_limiter
from research.cache import DiskCache
from research.models import ResearcherMetrics

logger = logging.getLogger(__name__)

S2_BASE = "https://api.semanticscholar.org/graph/v1"
S2_TTL = 7 * 24 * 3600  # 7 days
_MAX_S2_RETRIES = 5

# Default venues considered "top" for robotics/ML.
# Override via research.scoring.top_venues in config.json (applied by
# research.config.load_config -> set_top_venues).
DEFAULT_TOP_VENUES = {
    "icra", "iros", "rss", "corl",
    "neurips", "nips", "icml", "iclr",
    "cvpr", "iccv", "eccv",
    "aaai", "ijcai",
    "ral", "t-ro",
    "science robotics",
}

# Mutable at runtime — callers can replace via set_top_venues()
TOP_VENUES = set(DEFAULT_TOP_VENUES)


def set_top_venues(venues: Iterable[str]) -> None:
    """Override the set of venues considered 'top' (e.g., from config)."""
    global TOP_VENUES
    TOP_VENUES = {str(v).lower() for v in venues}


class S2RateLimitError(Exception):
    """Raised when S2 API rate limit retries are exhausted."""


def _s2_request(endpoint: str, api_key: str = "") -> Any:
    """Make a Semantic Scholar API request with exponential backoff on 429."""
    backoff_times = [5, 10, 20, 40, 60]
    for attempt in range(_MAX_S2_RETRIES + 1):
        s2_limiter.acquire()
        url = f"{S2_BASE}/{endpoint}"
        headers = {"User-Agent": "research-tool/1.0"}
        if api_key:
            headers["x-api-key"] = api_key
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            if e.code == 429:
                if attempt >= _MAX_S2_RETRIES:
                    raise S2RateLimitError(
                        f"S2 API rate limit: {_MAX_S2_RETRIES + 1} attempts exhausted for {endpoint}"
                    )
                wait = backoff_times[min(attempt, len(backoff_times) - 1)]
                logger.warning("[S2] 限速, 等待 %ds (第 %d/%d 次)...", wait, attempt + 1, _MAX_S2_RETRIES)
                time.sleep(wait)
                continue
            raise


def _score_author_candidate(
    candidate: dict[str, Any],
    query_name: str,
    affiliation_hint: str = "",
) -> float:
    """Score an S2 author candidate for disambiguation.

    Scoring: name match (max 6), affiliation match (max 5),
    paper count (log-scaled, max 8), h-index (max 6).

    Bibliometric signals are weighted higher than name matching to avoid
    selecting low-output exact-name matches over prolific abbreviated-name authors.
    """
    score = 0.0
    c_name = candidate.get("name") or ""

    # Name match: 6 (exact), 5 (case-insensitive), 4 (word overlap)
    if c_name == query_name:
        score += 6
    elif c_name.lower() == query_name.lower():
        score += 5
    elif _names_match(query_name, c_name):
        score += 4

    # Affiliation match
    if affiliation_hint:
        hint_lower = affiliation_hint.lower()
        affiliations = candidate.get("affiliations") or []
        for aff in affiliations:
            if hint_lower in aff.lower() or aff.lower() in hint_lower:
                score += 5
                break

    # Paper count (log-scaled, max 8)
    paper_count = candidate.get("paperCount") or 0
    if paper_count > 0:
        score += min(8.0, math.log10(paper_count + 1) * 3)

    # h-index (max 6)
    h_index = candidate.get("hIndex") or 0
    if h_index > 0:
        score += min(6.0, h_index / 20.0 * 6)

    return score


def search_author(
    name: str,
    affiliation: str = "",
    api_key: str = "",
    cache: DiskCache | None = None,
) -> dict[str, Any] | None:
    """Search for an author by name, return the best match after disambiguation."""
    cache_key = f"s2_author:{name}:{affiliation}" if affiliation else f"s2_author:{name}"
    if cache:
        cached = cache.get("api/semantic_scholar", cache_key, ttl_seconds=S2_TTL)
        if cached is not None:
            logger.info(f"[S2] 缓存命中: {name}")
            return cached

    logger.info(f"[S2] 搜索作者: {name}" + (f" (affiliation: {affiliation})" if affiliation else ""))
    encoded = urllib.parse.quote(name)
    try:
        data = _s2_request(
            f"author/search?query={encoded}&limit=5&fields=authorId,name,hIndex,"
            f"citationCount,paperCount,affiliations,homepage,url",
            api_key,
        )
    except Exception as e:
        logger.error(f"[S2] 作者搜索失败: {e}")
        return None

    if not data or not data.get("data"):
        logger.warning(f"[S2] 未找到作者: {name}")
        return None

    candidates = data["data"]
    if len(candidates) == 1:
        author = candidates[0]
    else:
        # Score and rank candidates
        scored = []
        for c in candidates:
            s = _score_author_candidate(c, name, affiliation)
            scored.append((s, c))
            logger.debug(
                "[S2] 候选: %s (score=%.1f, h=%s, papers=%s, aff=%s)",
                c.get("name"), s, c.get("hIndex"), c.get("paperCount"),
                c.get("affiliations"),
            )
        scored.sort(key=lambda x: x[0], reverse=True)
        author = scored[0][1]
        logger.info(
            "[S2] 选择: %s (score=%.1f, h=%s) 从 %d 个候选中",
            author.get("name"), scored[0][0], author.get("hIndex"), len(candidates),
        )

    if cache:
        cache.put("api/semantic_scholar", cache_key, author)
    return author


def get_author_by_id(
    author_id: str,
    api_key: str = "",
    cache: DiskCache | None = None,
) -> dict[str, Any] | None:
    """Fetch an author directly by Semantic Scholar author ID."""
    cache_key = f"s2_author_by_id:{author_id}"
    if cache:
        cached = cache.get("api/semantic_scholar", cache_key, ttl_seconds=S2_TTL)
        if cached is not None:
            logger.info(f"[S2] 作者ID缓存命中: {author_id}")
            return cached

    logger.info(f"[S2] 通过ID获取作者: {author_id}")
    try:
        data = _s2_request(
            f"author/{author_id}?fields=authorId,name,hIndex,"
            f"citationCount,paperCount,affiliations,homepage,url",
            api_key,
        )
    except Exception as e:
        logger.error(f"[S2] 通过ID获取作者失败: {e}")
        return None

    if not data or not data.get("authorId"):
        logger.warning(f"[S2] 未找到作者ID: {author_id}")
        return None

    if cache:
        cache.put("api/semantic_scholar", cache_key, data)
    return data


def search_paper_by_title(
    title: str,
    api_key: str = "",
    cache: DiskCache | None = None,
) -> dict[str, Any] | None:
    """Search for a paper by title, return the first match with authors."""
    cache_key = f"s2_paper_search:{title}"
    if cache:
        cached = cache.get("api/semantic_scholar", cache_key, ttl_seconds=S2_TTL)
        if cached is not None:
            logger.info(f"[S2] 论文标题搜索缓存命中: {title}")
            return cached

    logger.info(f"[S2] 按标题搜索论文: {title}")
    encoded = urllib.parse.quote(title)
    try:
        data = _s2_request(
            f"paper/search?query={encoded}&limit=3&fields=paperId,title,year,authors,citationCount",
            api_key,
        )
    except Exception as e:
        logger.error(f"[S2] 论文标题搜索失败: {e}")
        return None

    if not data or not data.get("data"):
        logger.warning(f"[S2] 未找到论文: {title}")
        return None

    paper = data["data"][0]
    if cache:
        cache.put("api/semantic_scholar", cache_key, paper)
    return paper


def resolve_author_by_paper(
    author_name: str,
    paper_hint: str,
    api_key: str = "",
    cache: DiskCache | None = None,
) -> dict[str, Any] | None:
    """Resolve an author by looking up a known paper and matching the author name.

    paper_hint can be an arXiv ID (e.g. 2301.12597), DOI (starts with 10.),
    or a paper title (fallback to title search).
    """
    cache_key = f"s2_author_by_paper:{author_name}:{paper_hint}"
    if cache:
        cached = cache.get("api/semantic_scholar", cache_key, ttl_seconds=S2_TTL)
        if cached is not None:
            logger.info(f"[S2] 论文反查缓存命中: {author_name} via {paper_hint}")
            return cached

    # Determine paper_hint type and fetch paper
    paper = None
    if (re.match(r"\d{4}\.\d+", paper_hint)
            or re.match(r"^[a-z-]+(\.[A-Za-z]{2})?/\d{7}", paper_hint, re.IGNORECASE)
            or paper_hint.startswith("10.")):
        # arXiv ID (new or old style) or DOI — get_paper_by_id normalizes both
        paper = get_paper_by_id(paper_hint, api_key=api_key, cache=cache)
    else:
        # Title search
        paper = search_paper_by_title(paper_hint, api_key=api_key, cache=cache)

    if not paper:
        logger.warning(f"[S2] 论文反查: 未找到论文 {paper_hint}")
        return None

    # Find matching author in paper's author list
    authors = paper.get("authors") or []
    matched_id = None
    for a in authors:
        a_name = a.get("name", "")
        a_id = a.get("authorId", "")
        if not a_id:
            continue
        if a_name.lower() == author_name.lower() or _names_match(author_name, a_name):
            matched_id = a_id
            logger.info(f"[S2] 论文反查: 匹配到 {a_name} (ID: {a_id})")
            break

    if not matched_id:
        logger.warning(
            f"[S2] 论文反查: 在论文 {paper.get('title', '')} 的作者中未找到 {author_name}"
        )
        return None

    # Fetch full author record
    author = get_author_by_id(matched_id, api_key=api_key, cache=cache)
    if author and cache:
        cache.put("api/semantic_scholar", cache_key, author)
    return author


def get_author_papers(
    author_id: str,
    api_key: str = "",
    limit: int = 500,
    cache: DiskCache | None = None,
) -> list[dict[str, Any]]:
    """Get papers for an author with citation counts and venue info."""
    cache_key = f"s2_papers:{author_id}:{limit}"
    if cache:
        cached = cache.get("api/semantic_scholar", cache_key, ttl_seconds=S2_TTL)
        if cached is not None:
            logger.info(f"[S2] 论文缓存命中: {author_id}")
            return cached

    logger.info(f"[S2] 获取作者 {author_id} 的论文...")
    all_papers: list[dict[str, Any]] = []
    offset = 0
    batch = min(limit, 500)

    while offset < limit:
        try:
            data = _s2_request(
                f"author/{author_id}/papers?offset={offset}&limit={batch}"
                f"&fields=paperId,title,year,citationCount,venue,authors,"
                f"externalIds,publicationTypes,abstract",
                api_key,
            )
        except Exception as e:
            logger.error(f"[S2] 获取论文失败: {e}")
            break

        papers = data.get("data", [])
        if not papers:
            break
        all_papers.extend(papers)
        offset += len(papers)
        if len(papers) < batch:
            break

    if cache and all_papers:
        cache.put("api/semantic_scholar", cache_key, all_papers)

    logger.info(f"[S2] 作者 {author_id}: 获取到 {len(all_papers)} 篇论文")
    return all_papers


def _venue_is_top(venue: str) -> bool:
    """Whether a venue string matches any top-venue abbreviation on word boundaries.

    Tokenizes both the venue and each abbreviation on non-alphanumerics, then
    checks for the abbreviation's tokens as a contiguous run within the venue's
    tokens. This avoids substring false positives (e.g. "ral" in "neural").
    """
    venue_tokens = [t for t in re.split(r"[^a-z0-9]+", venue) if t]
    if not venue_tokens:
        return False
    for tv in TOP_VENUES:
        tv_tokens = [t for t in re.split(r"[^a-z0-9]+", tv) if t]
        if not tv_tokens:
            continue
        n = len(tv_tokens)
        for i in range(len(venue_tokens) - n + 1):
            if venue_tokens[i:i + n] == tv_tokens:
                return True
    return False


def build_metrics(
    author_data: dict[str, Any],
    papers: list[dict[str, Any]],
) -> ResearcherMetrics:
    """Build ResearcherMetrics from S2 author data and papers."""
    import datetime
    current_year = datetime.datetime.now().year

    h_index = author_data.get("hIndex") or 0
    total_citations = author_data.get("citationCount") or 0
    paper_count = author_data.get("paperCount") or 0
    affiliations = author_data.get("affiliations") or []

    # Calculate recent citations (5yr)
    recent_citations = 0
    top_venue_count = 0
    years = []
    for p in papers:
        year = p.get("year") or 0
        if year:
            years.append(year)
        cites = p.get("citationCount") or 0
        if year and year >= current_year - 5:
            recent_citations += cites
        venue = (p.get("venue") or "").lower()
        # Word-boundary match: tokenize the venue on non-alphanumerics and look
        # for each top-venue abbreviation as a contiguous run of whole tokens,
        # so e.g. "ral" does not falsely match inside "neural".
        if _venue_is_top(venue):
            top_venue_count += 1

    first_year = min(years) if years else 0
    latest_year = max(years) if years else 0

    return ResearcherMetrics(
        h_index=h_index,
        total_citations=total_citations,
        recent_citations_5yr=recent_citations,
        paper_count=paper_count,
        top_venue_count=top_venue_count,
        current_affiliation=affiliations[0] if affiliations else "",
        first_paper_year=first_year,
        latest_paper_year=latest_year,
    )


def get_paper_by_id(
    paper_id: str,
    api_key: str = "",
    cache: DiskCache | None = None,
) -> dict[str, Any] | None:
    """Resolve arXiv ID, DOI, or S2 paper ID to full S2 paper record."""
    cache_key = f"s2_paper:{paper_id}"
    if cache:
        cached = cache.get("api/semantic_scholar", cache_key, ttl_seconds=S2_TTL)
        if cached is not None:
            logger.info(f"[S2] 论文缓存命中: {paper_id}")
            return cached

    logger.info(f"[S2] 查找论文: {paper_id}")
    # Determine ID prefix for S2 API
    original_id = paper_id
    stripped = paper_id
    if paper_id.startswith("10."):
        s2_id = f"DOI:{paper_id}"
    elif re.match(r"^\d{4}\.\d+", paper_id):
        # Strip arXiv version suffix (e.g., 2301.12597v2 → 2301.12597)
        stripped = re.sub(r"v\d+$", "", paper_id)
        s2_id = f"ARXIV:{stripped}"
    elif re.match(r"^[a-z-]+(\.[A-Za-z]{2})?/\d{7}", paper_id, re.IGNORECASE):
        # Old-style arXiv ID (e.g. math/0211159, cs.RO/0211159)
        stripped = re.sub(r"v\d+$", "", paper_id)
        s2_id = f"ARXIV:{stripped}"
    else:
        s2_id = paper_id  # assume S2 paper ID

    fields = "paperId,title,year,citationCount,venue,authors,abstract,externalIds"
    try:
        data = _s2_request(f"paper/{s2_id}?fields={fields}", api_key)
    except Exception as e:
        logger.error(f"[S2] 查找论文失败: {e}")
        data = None

    # Fallback: if stripped version failed and original had version suffix, retry with full ID
    if (not data or not data.get("paperId")) and stripped != original_id and "v" in original_id:
        logger.info(f"[S2] 无版本号未找到，尝试完整 ID: {original_id}")
        try:
            data = _s2_request(f"paper/ARXIV:{original_id}?fields={fields}", api_key)
        except Exception as e:
            logger.error(f"[S2] 重试查找论文失败: {e}")
            data = None

    if not data or not data.get("paperId"):
        logger.warning(f"[S2] 未找到论文: {paper_id}")
        return None

    if cache:
        cache.put("api/semantic_scholar", cache_key, data)
    return data


def get_paper_citations(
    paper_id: str,
    limit: int = 50,
    api_key: str = "",
    cache: DiskCache | None = None,
) -> list[dict[str, Any]]:
    """Get papers that CITE this paper (forward citations), sorted by citation count."""
    cache_key = f"s2_citations:{paper_id}:{limit}"
    if cache:
        cached = cache.get("api/semantic_scholar", cache_key, ttl_seconds=S2_TTL)
        if cached is not None:
            logger.info(f"[S2] 引用缓存命中: {paper_id}")
            return cached

    logger.info(f"[S2] 获取论文 {paper_id} 的引用...")
    try:
        data = _s2_request(
            f"paper/{paper_id}/citations?fields=paperId,title,year,"
            f"citationCount,venue,authors&limit={limit}",
            api_key,
        )
    except Exception as e:
        logger.error(f"[S2] 获取引用失败: {e}")
        return []

    citations = []
    for item in data.get("data", []):
        citing = item.get("citingPaper", {})
        if citing and citing.get("title"):
            citations.append(citing)

    # Sort by citation count descending
    citations.sort(key=lambda x: x.get("citationCount") or 0, reverse=True)

    if cache and citations:
        cache.put("api/semantic_scholar", cache_key, citations)

    logger.info(f"[S2] 论文 {paper_id}: 获取到 {len(citations)} 篇引用")
    return citations


def get_paper_references(
    paper_id: str,
    limit: int = 50,
    api_key: str = "",
    cache: DiskCache | None = None,
) -> list[dict[str, Any]]:
    """Get papers CITED BY this paper (backward references)."""
    cache_key = f"s2_references:{paper_id}:{limit}"
    if cache:
        cached = cache.get("api/semantic_scholar", cache_key, ttl_seconds=S2_TTL)
        if cached is not None:
            logger.info(f"[S2] 参考文献缓存命中: {paper_id}")
            return cached

    logger.info(f"[S2] 获取论文 {paper_id} 的参考文献...")
    try:
        data = _s2_request(
            f"paper/{paper_id}/references?fields=paperId,title,year,"
            f"citationCount,venue,authors&limit={limit}",
            api_key,
        )
    except Exception as e:
        logger.error(f"[S2] 获取参考文献失败: {e}")
        return []

    references = []
    for item in data.get("data", []):
        cited = item.get("citedPaper", {})
        if cited and cited.get("title"):
            references.append(cited)

    # Sort by citation count descending
    references.sort(key=lambda x: x.get("citationCount") or 0, reverse=True)

    if cache and references:
        cache.put("api/semantic_scholar", cache_key, references)

    logger.info(f"[S2] 论文 {paper_id}: 获取到 {len(references)} 篇参考文献")
    return references


def _names_match(query_name: str, candidate_name: str) -> bool:
    """Word-level name matching: last name must match, initials must be compatible.

    Prevents false positives like "Lee" matching "Leek" or "Li" matching "Eliana".
    """
    q_words = query_name.lower().split()
    c_words = candidate_name.lower().split()
    if not q_words or not c_words:
        return False
    # Last name must match exactly
    if q_words[-1] != c_words[-1]:
        return False
    # If only last name, that's enough
    if len(q_words) == 1 or len(c_words) == 1:
        return True
    # Check first name / initials compatibility
    q_first = q_words[:-1]
    c_first = c_words[:-1]
    for qf, cf in zip(q_first, c_first):
        # Strip trailing periods from initials (e.g., "S." → "s")
        qf = qf.rstrip(".")
        cf = cf.rstrip(".")
        if not qf or not cf:
            continue
        # Either full match, or one is an initial of the other
        if qf == cf:
            continue
        if len(qf) == 1 and cf.startswith(qf):
            continue
        if len(cf) == 1 and qf.startswith(cf):
            continue
        return False
    return True


def get_coauthor_data(
    author_id: str,
    papers: list[dict[str, Any]],
    author_name: str,
) -> list[dict[str, Any]]:
    """Analyze co-authorship patterns from paper data.

    Returns a list of co-author records with collaboration statistics.
    """
    coauthor_stats: dict[str, dict[str, Any]] = {}

    for p in papers:
        authors = p.get("authors") or []
        year = p.get("year") or 0
        if not authors or not year:
            continue

        author_names = [a.get("name", "") for a in authors]
        # Find advisor position
        advisor_pos = -1
        for i, a in enumerate(authors):
            if _names_match(author_name, a.get("name", "")):
                advisor_pos = i
                break
        if advisor_pos < 0:
            continue

        is_last = advisor_pos == len(authors) - 1

        for i, a in enumerate(authors):
            ca_name = a.get("name", "")
            ca_id = a.get("authorId", "")
            if not ca_name or _names_match(author_name, ca_name):
                continue

            if ca_name not in coauthor_stats:
                coauthor_stats[ca_name] = {
                    "name": ca_name,
                    "author_id": ca_id,
                    "total_collabs": 0,
                    "first_author_with_advisor_last": 0,
                    "years": [],
                }

            stats = coauthor_stats[ca_name]
            stats["total_collabs"] += 1
            stats["years"].append(year)
            # First author + advisor is last author → strong student signal
            if i == 0 and is_last:
                stats["first_author_with_advisor_last"] += 1

    # Convert to list and sort by signal strength
    results = []
    for ca_name, stats in coauthor_stats.items():
        stats["collab_start"] = min(stats["years"]) if stats["years"] else 0
        stats["collab_end"] = max(stats["years"]) if stats["years"] else 0
        stats["collab_span"] = stats["collab_end"] - stats["collab_start"]
        results.append(stats)

    results.sort(key=lambda x: x["first_author_with_advisor_last"], reverse=True)
    return results
