"""ArXiv API client: shared Client, Result adapters, and full-text extraction."""

from __future__ import annotations

import logging
import re
import time
import urllib.request

import arxiv

from common.html_text import html_to_text
from research.apis.rate_limiter import arxiv_limiter
from research.cache import DiskCache
from research.models import Paper

logger = logging.getLogger(__name__)

ARXIV_API_TTL = 7 * 24 * 3600  # 7 days

# Conservative vs arxiv defaults (page_size=100, delay=3s, retries=3).
_CLIENT_PAGE_SIZE = 100
_CLIENT_DELAY_SECONDS = 5.0
_CLIENT_NUM_RETRIES = 5

_ARXIV_MAX_RETRIES = 3
_ARXIV_BASE_DELAY = 10  # seconds; exponential backoff on HTTP 429/503

_ARXIV_HTML_SKIP = {
    "script", "style", "nav", "header", "footer", "figure", "figcaption",
}


def make_arxiv_client(
    page_size: int = _CLIENT_PAGE_SIZE,
    delay_seconds: float = _CLIENT_DELAY_SECONDS,
    num_retries: int = _CLIENT_NUM_RETRIES,
) -> arxiv.Client:
    """Shared arXiv client (page_size 100, delay 5s, 5 retries)."""
    return arxiv.Client(
        page_size=page_size,
        delay_seconds=delay_seconds,
        num_retries=num_retries,
    )


def iter_arxiv_results(
    client: arxiv.Client,
    search: arxiv.Search,
    *,
    max_retries: int = _ARXIV_MAX_RETRIES,
    base_delay: float = _ARXIV_BASE_DELAY,
):
    """Yield ``arxiv.Result`` rows with limiter + retry on HTTP 429/503.

    On a mid-stream transient error the query is restarted (the arXiv client
    cannot resume) and already-yielded rows are skipped.
    """
    emitted = 0
    for attempt in range(max_retries):
        arxiv_limiter.acquire()
        try:
            seen = 0
            for result in client.results(search):
                seen += 1
                if seen <= emitted:
                    continue
                emitted += 1
                yield result
            return
        except arxiv.HTTPError as e:
            status = getattr(e, "status", 0)
            if status in (429, 503) and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    "arXiv HTTP %d, %d秒后重试 (第%d/%d次)...",
                    status, delay, attempt + 1, max_retries,
                )
                time.sleep(delay)
                continue
            raise


def arxiv_id_from_result(result: arxiv.Result) -> str:
    """Normalize an arXiv id from ``Result.entry_id`` (keeps old ``cs/0112017`` ids)."""
    entry_id = result.entry_id or ""
    if "/abs/" in entry_id:
        return entry_id.split("/abs/")[-1]
    return entry_id.split("/")[-1]


def _paper_from_arxiv_result(
    result: arxiv.Result,
    *,
    author_limit: int | None = 10,
) -> dict:
    """Scout-shaped paper dict from an ``arxiv.Result``.

    Profiler ``Paper`` objects go through ``paper_model_from_arxiv_result``.
    """
    arxiv_id = arxiv_id_from_result(result)
    authors = [a.name for a in result.authors]
    if author_limit is not None:
        authors = authors[:author_limit]
    published = ""
    if result.published:
        published = result.published.strftime("%Y-%m-%d")
    return {
        "paper_id": arxiv_id,
        "arxiv_id": arxiv_id,
        "source": "arxiv",
        "title": (result.title or "").replace("\n", " ").strip(),
        "authors": authors,
        "abstract": (result.summary or "").replace("\n", " ").strip(),
        "categories": list(result.categories or []),
        "published": published,
        "url": result.entry_id or "",
        "pdf_url": result.pdf_url or "",
        "comment": (result.comment or "").strip(),
        "journal_ref": (result.journal_ref or "").strip(),
        "venue": "",
    }


paper_from_arxiv_result = _paper_from_arxiv_result


def paper_model_from_arxiv_result(result: arxiv.Result) -> Paper:
    """Profiler ``Paper`` adapter (all authors; no scout-only fields)."""
    d = _paper_from_arxiv_result(result, author_limit=None)
    return Paper(
        arxiv_id=d["arxiv_id"],
        title=d["title"],
        abstract=d["abstract"],
        authors=d["authors"],
        published=d["published"],
        categories=d["categories"],
        pdf_url=d["pdf_url"],
    )


def search_papers_by_author(
    author_name: str,
    max_results: int = 100,
    cache: DiskCache | None = None,
) -> list[Paper]:
    """Search ArXiv for papers by a given author name."""
    cache_key = f"arxiv_author:{author_name}:{max_results}"
    if cache:
        cached = cache.get("api/arxiv", cache_key, ttl_seconds=ARXIV_API_TTL)
        if cached is not None:
            logger.info(f"[ArXiv] 缓存命中: {author_name}")
            return [Paper.from_dict(p) for p in cached]

    logger.info(f"[ArXiv] 搜索作者: {author_name} (max={max_results})")

    query = f'au:"{author_name}"'
    client = make_arxiv_client()
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    papers = []
    truncated = False
    try:
        for result in iter_arxiv_results(client, search):
            papers.append(paper_model_from_arxiv_result(result))
    except Exception as e:
        logger.error(f"[ArXiv] 搜索失败: {e}")
        if not papers:
            raise
        # Partial list: surface what we have for this run only, but do NOT
        # cache it — a truncated list must not be served for the next 7 days.
        truncated = True
        logger.warning(
            f"[ArXiv] 结果被截断，返回部分列表且跳过缓存: {author_name} ({len(papers)} 篇)"
        )

    if cache and papers and not truncated:
        cache.put("api/arxiv", cache_key, [p.to_dict() for p in papers])

    logger.info(f"[ArXiv] 找到 {len(papers)} 篇论文: {author_name}")
    return papers


def download_fulltext(
    arxiv_id: str,
    pdf_url: str = "",
    cache: DiskCache | None = None,
) -> str:
    """Download full text from ArXiv, trying HTML first, then PDF fallback.

    ArXiv provides HTML versions for many recent papers at:
        https://arxiv.org/html/{arxiv_id}
    This is preferred over PDF because it's cleaner text without layout artifacts.
    """
    cache_key = f"fulltext:{arxiv_id}"
    if cache:
        cached = cache.get("api/pdfs", cache_key)  # Reuse pdfs namespace, no TTL
        if cached is not None:
            logger.info(f"[全文] 缓存命中: {arxiv_id}")
            return cached

    text = ""

    # 1. Try HTML first
    text = _download_html_text(arxiv_id)

    # 2. Fall back to PDF if HTML failed or returned too little text
    if len(text) < 500:
        logger.info(f"[全文] HTML 不可用或内容过少，尝试 PDF: {arxiv_id}")
        text = _download_pdf_text(arxiv_id, pdf_url)

    if cache and text:
        cache.put("api/pdfs", cache_key, text)

    return text


def _download_html_text(arxiv_id: str) -> str:
    """Try to download and extract text from ArXiv HTML version."""
    # Normalize arxiv_id (remove version suffix for HTML URL)
    clean_id = re.sub(r'v\d+$', '', arxiv_id)
    url = f"https://arxiv.org/html/{clean_id}"

    logger.info(f"[HTML] 尝试下载: {url}")
    arxiv_limiter.acquire()

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "research-tool/1.0 (academic research; mailto:user@example.com)",
        })
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status != 200:
                return ""
            html_bytes = resp.read()
            # Try to detect encoding
            content_type = resp.headers.get("Content-Type", "")
            if "charset=" in content_type:
                charset = content_type.split("charset=")[-1].strip()
            else:
                charset = "utf-8"
            html_text = html_bytes.decode(charset, errors="replace")

        text = html_to_text(html_text, skip_tags=_ARXIV_HTML_SKIP)

        logger.info(f"[HTML] 提取完成: {arxiv_id} ({len(text)} chars)")
        return text

    except urllib.error.HTTPError as e:
        if e.code == 404:
            logger.info(f"[HTML] 此论文无 HTML 版本: {arxiv_id}")
        else:
            logger.warning(f"[HTML] 下载失败 {arxiv_id}: HTTP {e.code}")
        return ""
    except Exception as e:
        logger.warning(f"[HTML] 下载/解析失败 {arxiv_id}: {e}")
        return ""


def _download_pdf_text(arxiv_id: str, pdf_url: str = "") -> str:
    """Download PDF from ArXiv and extract text using PyMuPDF."""
    logger.info(f"[PDF] 下载: {arxiv_id}")
    arxiv_limiter.acquire()

    try:
        import fitz  # PyMuPDF
    except ImportError:
        logger.error("[PDF] 需要安装 PyMuPDF: pip install PyMuPDF")
        return ""

    try:
        url = pdf_url if pdf_url else f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        req = urllib.request.Request(url, headers={
            "User-Agent": "research-tool/1.0 (academic research; mailto:user@example.com)",
        })
        with urllib.request.urlopen(req, timeout=60) as resp:
            pdf_bytes = resp.read()

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        text_parts = []
        for page in doc:
            text_parts.append(page.get_text())
        doc.close()
        full_text = "\n".join(text_parts)

        full_text = re.sub(r'\n{3,}', '\n\n', full_text)
        full_text = full_text.strip()

        logger.info(f"[PDF] 提取完成: {arxiv_id} ({len(full_text)} chars)")
        return full_text

    except Exception as e:
        logger.error(f"[PDF] 下载/解析失败 {arxiv_id}: {e}")
        return ""
