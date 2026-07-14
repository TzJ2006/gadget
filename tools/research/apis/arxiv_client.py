"""ArXiv API client for searching papers and extracting full text."""

from __future__ import annotations

import logging
import re
import urllib.request
from html.parser import HTMLParser
from typing import Any

import arxiv

from research.apis.rate_limiter import arxiv_limiter
from research.cache import DiskCache
from research.models import Paper

logger = logging.getLogger(__name__)

ARXIV_API_TTL = 7 * 24 * 3600  # 7 days


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
    arxiv_limiter.acquire()

    query = f'au:"{author_name}"'
    client = arxiv.Client(page_size=100, delay_seconds=3.0, num_retries=3)
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.SubmittedDate,
        sort_order=arxiv.SortOrder.Descending,
    )

    papers = []
    truncated = False
    try:
        for result in client.results(search):
            paper = Paper(
                arxiv_id=result.entry_id.split("/abs/")[-1] if "/abs/" in result.entry_id else result.entry_id.split("/")[-1],
                title=result.title.replace("\n", " ").strip(),
                abstract=result.summary.replace("\n", " ").strip(),
                authors=[a.name for a in result.authors],
                published=result.published.strftime("%Y-%m-%d") if result.published else "",
                categories=[c for c in result.categories],
                pdf_url=result.pdf_url or "",
            )
            papers.append(paper)
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


class _ArxivHTMLTextExtractor(HTMLParser):
    """Extract readable text from ArXiv HTML papers."""

    SKIP_TAGS = {"script", "style", "nav", "header", "footer", "figure", "figcaption"}

    def __init__(self):
        super().__init__()
        self._text_parts: list[str] = []
        self._skip_depth = 0
        self._in_article = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        cls = attrs_dict.get("class", "")
        # Focus on article content
        if tag == "article" or "ltx_document" in cls or "ltx_page_main" in cls:
            self._in_article = True
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in ("p", "div", "h1", "h2", "h3", "h4", "section", "li"):
            self._text_parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth == 0:
            self._text_parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._text_parts)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()


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

        # Parse HTML and extract text
        extractor = _ArxivHTMLTextExtractor()
        extractor.feed(html_text)
        text = extractor.get_text()

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
