"""Multi-source paper search: arXiv, bioRxiv, PubMed."""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from pathlib import Path

from common.io import atomic_write

from research.scout.config import (
    PAPERS_CACHE_DIR,
    BIORXIV_MAX_PAGES,
    get_logger,
)

logger = get_logger()

# ─── arXiv client (shared with research.apis.arxiv_client) ──────────

def _make_arxiv_client():
    """Create an arXiv client with conservative rate limiting."""
    from research.apis.arxiv_client import make_arxiv_client
    return make_arxiv_client()


def _arxiv_results_with_retry(client, search):
    """Iterate arXiv results with retry on transient HTTP errors (429, 503)."""
    from research.apis.arxiv_client import iter_arxiv_results
    yield from iter_arxiv_results(client, search)


# ─── Venue detection ────────────────────────────────────────────────

_KNOWN_VENUES_RE = re.compile(
    r"(ICRA|IROS|CoRL|NeurIPS|NIPS|CVPR|ICCV|ECCV|ICML|ICLR|AAAI|IJCAI|RSS|"
    r"RAL|T-RO|RO-L|SIGGRAPH|ACL|EMNLP|NAACL|KDD|WWW|CHI|UIST|HRI)\s*\d{4}",
    re.IGNORECASE,
)


def _extract_venue(paper: dict) -> str:
    """Extract conference/journal name from comment/journal_ref."""
    for field in ("comment", "journal_ref"):
        text = paper.get(field, "")
        if not text:
            continue
        m = _KNOWN_VENUES_RE.search(text)
        if m:
            return m.group(0).strip()
    return ""


# ─── Paper ID helpers ───────────────────────────────────────────────

def paper_id(paper: dict) -> str:
    """Get the unified paper ID (compatible with paper_id and arxiv_id)."""
    return paper.get("paper_id") or paper.get("arxiv_id", "")


def paper_url(paper: dict) -> str:
    """Build URL based on paper source."""
    if paper.get("url"):
        return paper["url"]
    pid = paper_id(paper)
    src = paper.get("source", "arxiv")
    if src == "arxiv":
        return f"https://arxiv.org/abs/{pid}"
    elif src == "biorxiv":
        return f"https://doi.org/{pid.removeprefix('biorxiv:')}"
    elif src == "pubmed":
        return f"https://pubmed.ncbi.nlm.nih.gov/{pid.removeprefix('pmid:')}/"
    return ""


# ─── Search caching ─────────────────────────────────────────────────

def _search_cache_path(project_id: str, search_date: date,
                       conference: str | None = None,
                       author: str | None = None,
                       source: str | None = None) -> Path:
    """Search cache file path."""
    if conference:
        safe_conf = re.sub(r"[^a-zA-Z0-9_-]", "_", conference)
        return PAPERS_CACHE_DIR / f"{search_date.isoformat()}_{project_id}_{safe_conf}_search.json"
    if author:
        safe_author = re.sub(r"[^a-zA-Z0-9_-]", "_", author)
        return PAPERS_CACHE_DIR / f"{search_date.isoformat()}_{project_id}_{safe_author}_author_search.json"
    if source and source != "arxiv":
        return PAPERS_CACHE_DIR / f"{search_date.isoformat()}_{project_id}_{source}_search.json"
    return PAPERS_CACHE_DIR / f"{search_date.isoformat()}_{project_id}_search.json"


def load_search_cache(project: dict, search_date: date,
                      conference: str | None = None,
                      author: str | None = None,
                      source: str | None = None) -> list[dict] | None:
    """Return cached results if cache exists and keywords haven't changed."""
    cache_path = _search_cache_path(project["id"], search_date, conference, author, source)
    if not cache_path.exists():
        return None

    try:
        with open(cache_path, "r", encoding="utf-8") as f:
            cached = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    cached_kw = set(cached.get("_keywords", []))
    current_kw = set(project.get("search_keywords", []))
    if cached_kw != current_kw:
        return None

    return cached.get("papers", [])


def load_known_paper_ids(project_id: str, source: str | None = None) -> set[str]:
    """Scan cache dir to collect all cached paper_id / arxiv_id for a project."""
    known = set()
    if not PAPERS_CACHE_DIR.exists():
        return known
    # Anchor the date prefix ([0-9]*-*-*) so "*_{project_id}_..." can't
    # match a longer project id (e.g. "bar_foo" matching project "foo").
    if source and source != "arxiv":
        pattern = f"[0-9]*-*-*_{project_id}_{source}_search.json"
        suffix = f"_{project_id}_{source}_search.json"
    else:
        pattern = f"[0-9]*-*-*_{project_id}_search.json"
        suffix = f"_{project_id}_search.json"
    for cache_file in PAPERS_CACHE_DIR.glob(pattern):
        # Glob anchors the date prefix; confirm the project_id segment is
        # exact (the date prefix has no underscores, so the remainder must
        # match the suffix precisely) to rule out e.g. "bar_foo".
        # Date prefix is ISO (no underscores), so partition on the first "_"
        # isolates it; the remainder must equal the project/source suffix.
        _date_prefix, _, rest = cache_file.name.partition("_")
        if "_" + rest != suffix:
            continue
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            for p in data.get("papers", []):
                pid = p.get("paper_id") or p.get("arxiv_id", "")
                if pid:
                    known.add(pid)
        except (OSError, json.JSONDecodeError):
            continue
    return known


def save_search_cache(project: dict, search_date: date,
                      papers: list[dict],
                      conference: str | None = None,
                      author: str | None = None,
                      source: str | None = None) -> None:
    """Save search cache."""
    PAPERS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = _search_cache_path(project["id"], search_date, conference, author, source)
    data = {
        "_project_id": project["id"],
        "_keywords": project.get("search_keywords", []),
        "_date": search_date.isoformat(),
        "_cached_at": datetime.now().isoformat(),
        "papers": papers,
    }
    if conference:
        data["_conference"] = conference
    if author:
        data["_author"] = author
    if source:
        data["_source"] = source
    atomic_write(cache_path, json.dumps(data, ensure_ascii=False, indent=2))


# ─── arXiv search ───────────────────────────────────────────────────

def build_arxiv_query(project: dict, lookback_days: int = 7) -> str:
    """Build arXiv query string from project keywords and categories."""
    if project.get("arxiv_query_override"):
        return project["arxiv_query_override"]

    keywords = project.get("search_keywords", [])
    categories = project.get("arxiv_categories", [])

    if not keywords:
        logger.warning("项目 %s 没有 search_keywords", project["id"])
        return ""

    kw_part = " OR ".join(f'"{kw}"' if " " in kw else kw for kw in keywords)
    kw_query = f"({kw_part})" if len(keywords) > 1 else kw_part

    if categories:
        cat_part = " OR ".join(f"cat:{c}" for c in categories)
        cat_query = f"({cat_part})" if len(categories) > 1 else cat_part
        return f"{kw_query} AND {cat_query}"

    return kw_query


def search_arxiv(project: dict, lookback_days: int = 7,
                 max_results: int = 50,
                 known_ids: set[str] | None = None) -> list[dict] | None:
    """Search arXiv, return standardized paper list.

    Returns ``None`` on hard failure (e.g. the result iteration raised), so
    callers can distinguish a genuinely empty result from a broken search and
    avoid caching the latter as the authoritative daily result.
    """
    try:
        import arxiv
        from research.apis.arxiv_client import (
            arxiv_id_from_result,
            _paper_from_arxiv_result,
        )
    except ImportError:
        logger.error("请安装 arxiv: pip install arxiv")
        import sys; sys.exit(1)

    query = build_arxiv_query(project, lookback_days)
    if not query:
        return []

    logger.info("arXiv 搜索: %s", query)
    logger.info("回溯天数: %d, 最多结果: %d", lookback_days, max_results)

    client = _make_arxiv_client()
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    papers = []
    consecutive_known = 0
    skipped_known = 0
    try:
        for result in _arxiv_results_with_retry(client, search):
            submitted = result.published.date()
            cutoff = date.today() - timedelta(days=lookback_days)
            if submitted < cutoff:
                continue

            arxiv_id = arxiv_id_from_result(result)

            if known_ids and arxiv_id in known_ids:
                consecutive_known += 1
                skipped_known += 1
                if consecutive_known >= 5:
                    logger.info("连续遇到 %d 篇已缓存论文，停止搜索", consecutive_known)
                    break
                continue

            consecutive_known = 0

            paper = _paper_from_arxiv_result(result)
            paper["venue"] = _extract_venue(paper)
            papers.append(paper)
    except Exception as e:
        logger.warning("arXiv 搜索出错: %s", e)
        return None  # hard failure — do not cache as authoritative result

    if skipped_known:
        logger.info("跳过 %d 篇已缓存论文", skipped_known)
    logger.info("找到 %d 篇新论文 (项目: %s)", len(papers), project["id"])
    return papers


_CONF_BASE_RE = re.compile(
    r"((?:NeurIPS|NIPS|ICML|ICLR|CVPR|ICCV|ECCV|AAAI|IJCAI|ACL|EMNLP|NAACL|"
    r"ICRA|IROS|CoRL|RSS|KDD|WWW|CHI|UIST|HRI|SIGGRAPH|RAL|T-RO|"
    r"SIGMOD|VLDB|OSDI|SOSP|NSDI|PLDI|POPL)\s*\d{4})",
    re.IGNORECASE,
)


def _conference_matches(conference_lower: str, text: str) -> bool:
    """Flexible conference name matching against comment/journal_ref.

    Strategy (in order):
    1. Full substring match — e.g. "neurips 2024" in "Accepted at NeurIPS 2024"
    2. Extract base conference+year (e.g. "NeurIPS 2025" from "NeurIPS 2025 Datasets
       and Benchmarks") and check if that appears in text
    3. Token-based: check if all significant tokens appear
    """
    text_lower = text.lower()
    if not text_lower:
        return False

    # 1. Direct substring match
    if conference_lower in text_lower:
        return True

    # 2. Base conference+year match (handles track/workshop suffixes)
    base_match = _CONF_BASE_RE.search(conference_lower)
    if base_match and base_match.group(1).lower() in text_lower:
        return True

    # 3. Token-based fallback
    _FILLER = {"and", "the", "of", "on", "in", "for", "at", "track", "workshop"}
    tokens = [t for t in conference_lower.split() if t not in _FILLER and len(t) > 1]
    if not tokens:
        return False
    return all(t in text_lower for t in tokens)


def search_arxiv_conference(conference: str, project: dict | None = None,
                            max_results: int = 100) -> list[dict]:
    """Search papers from a specific conference via arXiv full-text + comment filter."""
    try:
        import arxiv
        from research.apis.arxiv_client import _paper_from_arxiv_result
    except ImportError:
        logger.error("请安装 arxiv: pip install arxiv")
        import sys; sys.exit(1)

    query = f'all:"{conference}"'
    if project:
        keywords = project.get("search_keywords", [])
        if keywords:
            kw_part = " OR ".join(f'"{kw}"' if " " in kw else kw for kw in keywords)
            kw_query = f"({kw_part})" if len(keywords) > 1 else kw_part
            query = f'{query} AND {kw_query}'

    logger.info("会议搜索: %s", query)
    logger.info("最多结果: %d", max_results)

    client = _make_arxiv_client()
    search = arxiv.Search(
        query=query,
        max_results=max_results * 3,
        sort_by=arxiv.SortCriterion.Relevance,
    )

    papers = []
    conf_lower = conference.lower()
    try:
        for result in _arxiv_results_with_retry(client, search):
            comment = (result.comment or "").strip()
            journal_ref = (result.journal_ref or "").strip()

            if (not _conference_matches(conf_lower, comment)
                    and not _conference_matches(conf_lower, journal_ref)):
                continue

            paper = _paper_from_arxiv_result(result)
            paper["venue"] = _extract_venue(paper) or conference
            papers.append(paper)

            if len(papers) >= max_results:
                break
    except Exception as e:
        logger.warning("arXiv 会议搜索出错: %s", e)

    logger.info("找到 %d 篇会议论文 (%s)", len(papers), conference)
    return papers


def search_arxiv_author(author: str, project: dict | None = None,
                        max_results: int = 100,
                        lookback_days: int | None = None) -> list[dict]:
    """Search papers by a specific author via arXiv au: query."""
    try:
        import arxiv
        from research.apis.arxiv_client import _paper_from_arxiv_result
    except ImportError:
        logger.error("请安装 arxiv: pip install arxiv")
        import sys; sys.exit(1)

    query = f'au:"{author}"'
    if project:
        keywords = project.get("search_keywords", [])
        if keywords:
            kw_part = " OR ".join(f'"{kw}"' if " " in kw else kw for kw in keywords)
            kw_query = f"({kw_part})" if len(keywords) > 1 else kw_part
            query = f'{query} AND {kw_query}'

    logger.info("作者搜索: %s", query)
    logger.info("最多结果: %d", max_results)

    cutoff = None
    if lookback_days is not None:
        cutoff = (datetime.now() - timedelta(days=lookback_days)).date()
        logger.info("回溯截止: %s", cutoff.isoformat())

    client = _make_arxiv_client()
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance,
    )

    papers = []
    try:
        for result in _arxiv_results_with_retry(client, search):
            pub_date = result.published.date()
            if cutoff and pub_date < cutoff:
                continue

            paper = _paper_from_arxiv_result(result)
            paper["venue"] = _extract_venue(paper)
            papers.append(paper)

            if len(papers) >= max_results:
                break
    except Exception as e:
        logger.warning("arXiv 作者搜索出错: %s", e)

    logger.info("找到 %d 篇论文 (作者: %s)", len(papers), author)
    return papers


# ─── bioRxiv search ─────────────────────────────────────────────────

def search_biorxiv(project: dict, lookback_days: int = 7,
                   max_results: int = 50,
                   known_ids: set[str] | None = None) -> list[dict] | None:
    """Search bioRxiv API with local keyword + category filtering.

    Returns ``None`` on hard failure (an API request raised), so a broken or
    partial paginated search is not cached as the authoritative daily result.
    """
    keywords = project.get("search_keywords", [])
    if not keywords:
        logger.warning("项目 %s 没有 search_keywords，跳过 bioRxiv 搜索", project["id"])
        return []

    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")

    biorxiv_categories = set(c.lower() for c in project.get("biorxiv_categories", []))
    kw_lower = [kw.lower() for kw in keywords]

    logger.info("bioRxiv 搜索: keywords=%s, dates=%s~%s", keywords, start_str, end_str)
    if biorxiv_categories:
        logger.info("bioRxiv 分类过滤: %s", biorxiv_categories)

    papers = []
    consecutive_known = 0
    skipped_known = 0
    cursor = 0
    hard_failure = False

    for page in range(BIORXIV_MAX_PAGES):
        api_url = f"https://api.biorxiv.org/details/biorxiv/{start_str}/{end_str}/{cursor}/json"
        logger.debug("bioRxiv API 请求: %s", api_url)

        try:
            req = urllib.request.Request(api_url, headers={"User-Agent": "research-scout/1.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            logger.warning("bioRxiv API 请求失败 (page %d): %s", page, e)
            hard_failure = True
            break

        collection = data.get("collection", [])
        if not collection:
            break

        for item in collection:
            doi = item.get("doi", "")
            if not doi:
                continue

            pid = f"biorxiv:{doi}"

            if known_ids and pid in known_ids:
                consecutive_known += 1
                skipped_known += 1
                if consecutive_known >= 5:
                    logger.info("bioRxiv: 连续遇到 %d 篇已缓存论文，停止搜索", consecutive_known)
                    break
                continue
            consecutive_known = 0

            category = item.get("category", "").lower()
            if biorxiv_categories and category not in biorxiv_categories:
                continue

            title = item.get("title", "")
            abstract = item.get("abstract", "")
            text_lower = (title + " " + abstract).lower()
            if not any(kw in text_lower for kw in kw_lower):
                continue

            authors_str = item.get("authors", "")
            authors = [a.strip() for a in authors_str.split(";") if a.strip()][:10]

            pub_date = item.get("date", "")

            paper = {
                "paper_id": pid,
                "source": "biorxiv",
                "title": title.replace("\n", " ").strip(),
                "authors": authors,
                "abstract": abstract.replace("\n", " ").strip(),
                "categories": [category] if category else [],
                "published": pub_date,
                "url": f"https://doi.org/{doi}",
                "pdf_url": f"https://www.biorxiv.org/content/{doi}v{item.get('version', '1')}.full.pdf",
                "comment": "",
                "journal_ref": item.get("published", ""),
                "venue": "",
            }
            papers.append(paper)

            if len(papers) >= max_results:
                break

        if consecutive_known >= 5 or len(papers) >= max_results:
            break

        # bioRxiv returns `total` as a JSON string (e.g. "4569") — coerce or the
        # int >= str comparison below raises TypeError and aborts the whole search.
        total = int(data.get("messages", [{}])[0].get("total", 0) or 0)
        cursor += len(collection)
        if cursor >= total:
            break

    if hard_failure:
        return None  # broken/partial search — do not cache as authoritative result

    if skipped_known:
        logger.info("bioRxiv: 跳过 %d 篇已缓存论文", skipped_known)
    logger.info("bioRxiv: 找到 %d 篇新论文 (项目: %s)", len(papers), project["id"])
    return papers


# ─── PubMed search ──────────────────────────────────────────────────

def _parse_pubmed_article(article_elem) -> dict | None:
    """Parse PubMed XML <PubmedArticle> element into standardized paper dict."""
    try:
        medline = article_elem.find("MedlineCitation")
        if medline is None:
            return None

        pmid_elem = medline.find("PMID")
        if pmid_elem is None or not pmid_elem.text:
            return None
        pmid = pmid_elem.text.strip()

        article = medline.find("Article")
        if article is None:
            return None

        title_elem = article.find("ArticleTitle")
        title = "".join(title_elem.itertext()).strip() if title_elem is not None else ""

        abstract_parts = []
        abstract_elem = article.find("Abstract")
        if abstract_elem is not None:
            for at in abstract_elem.findall("AbstractText"):
                label = at.get("Label", "")
                text = "".join(at.itertext()).strip()
                if label and text:
                    abstract_parts.append(f"{label}: {text}")
                elif text:
                    abstract_parts.append(text)
        abstract = " ".join(abstract_parts)

        authors = []
        author_list = article.find("AuthorList")
        if author_list is not None:
            for auth in author_list.findall("Author")[:10]:
                last = auth.findtext("LastName", "")
                fore = auth.findtext("ForeName", "")
                if last:
                    name = f"{fore} {last}".strip() if fore else last
                    authors.append(name)

        journal_elem = article.find("Journal")
        journal_name = ""
        if journal_elem is not None:
            title_e = journal_elem.find("Title")
            if title_e is not None and title_e.text:
                journal_name = title_e.text.strip()

        doi = ""
        article_ids = article_elem.find("PubmedData")
        if article_ids is not None:
            for aid in article_ids.findall(".//ArticleId"):
                if aid.get("IdType") == "doi" and aid.text:
                    doi = aid.text.strip()
                    break

        pub_date_elem = article.find(".//PubDate")
        pub_date = ""
        if pub_date_elem is not None:
            year = pub_date_elem.findtext("Year", "")
            month = pub_date_elem.findtext("Month", "01")
            day = pub_date_elem.findtext("Day", "01")
            try:
                if not month.isdigit():
                    month_map = {"jan": "01", "feb": "02", "mar": "03", "apr": "04",
                                 "may": "05", "jun": "06", "jul": "07", "aug": "08",
                                 "sep": "09", "oct": "10", "nov": "11", "dec": "12"}
                    month = month_map.get(month[:3].lower(), "01")
                if year:
                    pub_date = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
            except (ValueError, AttributeError):
                pub_date = year if year else ""

        url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        if doi:
            pdf_url = f"https://doi.org/{doi}"
        else:
            pdf_url = url

        return {
            "paper_id": f"pmid:{pmid}",
            "source": "pubmed",
            "title": title.replace("\n", " ").strip(),
            "authors": authors,
            "abstract": abstract.replace("\n", " ").strip(),
            "categories": [],
            "published": pub_date,
            "url": url,
            "pdf_url": pdf_url,
            "comment": "",
            "journal_ref": journal_name,
            "venue": journal_name,
        }
    except Exception as e:
        logger.debug("PubMed XML 解析失败: %s", e)
        return None


def search_pubmed(project: dict, lookback_days: int = 7,
                  max_results: int = 50,
                  known_ids: set[str] | None = None) -> list[dict] | None:
    """Search PubMed via esearch -> efetch two-step process.

    Returns ``None`` on hard failure (esearch errored, or an efetch batch
    failed leaving only partial results), so a broken search is not cached as
    the authoritative daily result.
    """
    keywords = project.get("search_keywords", [])
    if not keywords:
        logger.warning("项目 %s 没有 search_keywords，跳过 PubMed 搜索", project["id"])
        return []

    pubmed_journals = project.get("pubmed_journals", [])

    kw_terms = " OR ".join(f'"{kw}"[tiab]' for kw in keywords)
    query_parts = [f"({kw_terms})"]

    if pubmed_journals:
        journal_terms = " OR ".join(f'"{j}"[ta]' for j in pubmed_journals)
        query_parts.append(f"({journal_terms})")

    end_date = date.today()
    start_date = end_date - timedelta(days=lookback_days)
    date_range = f'("{start_date.strftime("%Y/%m/%d")}"[pdat]:"{end_date.strftime("%Y/%m/%d")}"[pdat])'
    query_parts.append(date_range)

    query = " AND ".join(query_parts)
    logger.info("PubMed 搜索: %s", query)

    esearch_url = (
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?"
        + urllib.parse.urlencode({
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "retmode": "json",
            "sort": "date",
        })
    )

    try:
        req = urllib.request.Request(esearch_url, headers={"User-Agent": "research-scout/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            esearch_data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning("PubMed esearch 失败: %s", e)
        return None  # hard failure — do not cache as authoritative result

    pmids = esearch_data.get("esearchresult", {}).get("idlist", [])
    if not pmids:
        logger.info("PubMed: 未找到结果")
        return []

    logger.info("PubMed: esearch 返回 %d 个 PMID", len(pmids))

    if known_ids:
        pmids = [p for p in pmids if f"pmid:{p}" not in known_ids]
        if not pmids:
            logger.info("PubMed: 所有结果均已缓存")
            return []

    papers = []
    hard_failure = False
    batch_size = 100
    for i in range(0, len(pmids), batch_size):
        batch = pmids[i:i + batch_size]
        efetch_url = (
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?"
            + urllib.parse.urlencode({
                "db": "pubmed",
                "id": ",".join(batch),
                "retmode": "xml",
            })
        )

        if i > 0:
            time.sleep(0.4)

        try:
            req = urllib.request.Request(efetch_url, headers={"User-Agent": "research-scout/1.0"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                xml_text = resp.read().decode("utf-8")
        except Exception as e:
            logger.warning("PubMed efetch 失败 (batch %d): %s", i // batch_size, e)
            hard_failure = True
            continue

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            logger.warning("PubMed XML 解析失败: %s", e)
            hard_failure = True
            continue

        for article_elem in root.findall("PubmedArticle"):
            paper = _parse_pubmed_article(article_elem)
            if paper:
                papers.append(paper)

    if hard_failure:
        return None  # partial/broken efetch — do not cache as authoritative result

    logger.info("PubMed: 找到 %d 篇论文 (项目: %s)", len(papers), project["id"])
    return papers


# ─── Multi-source search helper ─────────────────────────────────────

def search_source(project: dict, source: str, lookback: int,
                  max_results: int, no_cache: bool,
                  today: date) -> list[dict]:
    """Search a single source with cache support. Returns paper list."""
    if not no_cache:
        cached = load_search_cache(project, today, source=source)
        if cached is not None:
            logger.info("%s 搜索缓存命中: %s (%d 篇)", source, project["id"], len(cached))
            return cached

    if source == "arxiv":
        known_ids = load_known_paper_ids(project["id"])
        papers = search_arxiv(project, lookback, max_results, known_ids=known_ids)
    elif source == "biorxiv":
        known_ids = load_known_paper_ids(project["id"], source="biorxiv")
        papers = search_biorxiv(project, lookback, max_results, known_ids=known_ids)
    elif source == "pubmed":
        known_ids = load_known_paper_ids(project["id"], source="pubmed")
        papers = search_pubmed(project, lookback, max_results, known_ids=known_ids)
    else:
        logger.warning("未知来源: %s，跳过", source)
        return []

    # A searcher returns None on hard failure (vs [] for a genuinely empty
    # result). Only cache real successes so a failed/partial search isn't
    # frozen as the authoritative daily result; callers still get a list.
    if papers is None:
        logger.warning("%s 搜索失败: %s，不缓存", source, project["id"])
        return []

    save_search_cache(project, today, papers, source=source)
    return papers
