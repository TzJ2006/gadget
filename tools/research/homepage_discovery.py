"""Homepage-based student discovery for researcher profiler."""

from __future__ import annotations

import ipaddress
import logging
import socket
import urllib.parse
import urllib.request
import urllib.error
from html.parser import HTMLParser
from typing import Any

from research.apis.rate_limiter import web_limiter
from research.cache import DiskCache
from research.llm import call_llm, parse_json_response
from research.models import StudentCandidate
from research.prompts import HOMEPAGE_URL_PROMPT, HOMEPAGE_STUDENT_PROMPT

logger = logging.getLogger(__name__)

HOMEPAGE_TTL = 7 * 24 * 3600  # 7 days

_ALLOWED_SCHEMES = {"http", "https"}


def _is_safe_url(url: str) -> bool:
    """Validate URL against SSRF attacks by blocking private/internal IPs.

    Returns True if the URL is safe to fetch, False otherwise.
    """
    try:
        parsed = urllib.parse.urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in _ALLOWED_SCHEMES:
        logger.warning(f"[SSRF] Blocked disallowed scheme: {parsed.scheme}:// in {url}")
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except (socket.gaierror, OSError):
        logger.warning(f"[SSRF] DNS resolution failed for {hostname}")
        return False

    for _family, _type, _proto, _canonname, sockaddr in addr_info:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            logger.warning(f"[SSRF] Blocked private/internal IP {ip} for {url}")
            return False

    return True


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-validate each redirect target against SSRF rules.

    The initial _is_safe_url() check only covers the URL we were given;
    a malicious/compromised host can 30x-redirect to a private/internal
    address. This handler re-runs _is_safe_url on every redirect target.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _is_safe_url(newurl):
            raise urllib.error.HTTPError(
                newurl, code, "Blocked unsafe redirect target", headers, fp
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# Opener that applies the SSRF-aware redirect handler to all fetches.
_SAFE_OPENER = urllib.request.build_opener(_SafeRedirectHandler())


def _decode_response(raw: bytes, resp) -> str:
    """Decode raw response bytes honouring the page charset.

    Prefers the charset declared in the response headers, then falls back
    through a common chain (utf-8 → gbk → latin-1). GBK is important for
    Chinese university/department homepages. latin-1 with errors="replace"
    is the last resort since it never raises.
    """
    charsets: list[str] = []
    declared = None
    try:
        declared = resp.headers.get_content_charset()
    except Exception:
        declared = None
    if declared:
        charsets.append(declared)
    for fallback in ("utf-8", "gbk"):
        if fallback not in charsets:
            charsets.append(fallback)
    for charset in charsets:
        try:
            return raw.decode(charset)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("latin-1", errors="replace")


class _HomepageTextExtractor(HTMLParser):
    """Extract readable text and links from HTML pages.

    Strips scripts/styles/nav, extracts body text + link hrefs.
    Follows the pattern of _ArxivHTMLTextExtractor in arxiv_client.py.
    """

    SKIP_TAGS = {"script", "style", "nav", "header", "footer", "svg", "noscript"}

    # Hitting one of these clears the skip stack: an unclosed <nav>/<header>
    # earlier in the document must not swallow the entire body. Only true
    # document landmarks qualify — <article> is excluded because it legitimately
    # nests inside <footer>/<nav>, where clearing would leak boilerplate text.
    RECOVERY_TAGS = {"body", "main"}

    def __init__(self):
        super().__init__()
        self._text_parts: list[str] = []
        self._links: list[str] = []
        # Stack of open skip tags — a properly-closed </footer> pops only its
        # own region, so a nested <article> inside it stays skipped.
        self._skip_stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.RECOVERY_TAGS:
            # Recover from an unbalanced skip tag (e.g. <nav> with no </nav>).
            self._skip_stack.clear()
        if tag in self.SKIP_TAGS:
            self._skip_stack.append(tag)
            return
        if self._skip_stack:
            return
        attrs_dict = dict(attrs)
        if tag == "a":
            href = attrs_dict.get("href", "")
            if href and href.startswith("http"):
                self._links.append(href)

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and tag in self._skip_stack:
            # Pop the most recent matching skip region.
            for i in range(len(self._skip_stack) - 1, -1, -1):
                if self._skip_stack[i] == tag:
                    del self._skip_stack[i]
                    break
        if tag in ("p", "div", "h1", "h2", "h3", "h4", "h5", "li", "tr", "br", "section"):
            self._text_parts.append("\n")

    def handle_data(self, data):
        if not self._skip_stack:
            self._text_parts.append(data)

    def get_text(self) -> str:
        import re
        text = "".join(self._text_parts)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()

    def get_links(self) -> list[str]:
        return self._links


def fetch_homepage(
    url: str,
    cache: DiskCache | None = None,
) -> str:
    """Fetch a URL and extract text content. Cached in api/homepage namespace."""
    if not _is_safe_url(url):
        return ""

    cache_key = f"homepage:{url}"
    if cache:
        cached = cache.get("api/homepage", cache_key, ttl_seconds=HOMEPAGE_TTL)
        if cached is not None:
            logger.info(f"[Homepage] 缓存命中: {url}")
            return cached

    logger.info(f"[Homepage] 获取页面: {url}")
    web_limiter.acquire()

    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (research-tool/1.0; academic profiler)",
            "Accept": "text/html,application/xhtml+xml",
        })
        with _SAFE_OPENER.open(req, timeout=15) as resp:
            # Read up to 2MB
            raw = resp.read(2 * 1024 * 1024)
            html = _decode_response(raw, resp)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, UnicodeDecodeError) as e:
        logger.warning(f"[Homepage] 获取失败 {url}: {e}")
        return ""

    extractor = _HomepageTextExtractor()
    try:
        extractor.feed(html)
    except Exception as e:
        logger.warning(f"[Homepage] 解析失败 {url}: {e}")
        return ""

    text = extractor.get_text()

    # Truncate very long pages
    if len(text) > 50000:
        text = text[:50000] + "\n...[截断]"

    if cache and text:
        cache.put("api/homepage", cache_key, text)

    logger.info(f"[Homepage] 提取完成: {url} ({len(text)} chars)")
    return text


def discover_homepage_urls(
    name: str,
    affiliation: str,
    s2_homepage: str = "",
    cache: DiskCache | None = None,
    backend: str = "claude_cli",
) -> list[str]:
    """Multi-strategy URL discovery for a researcher's homepage/lab page.

    1. Use S2 homepage field if available
    2. Use LLM to suggest likely URLs based on name + affiliation
    3. Return deduplicated list

    URL suggestion intentionally uses the cheap "haiku" model regardless of
    the profiler's configured model — this is a low-stakes guessing step and
    not worth a larger model's cost, so there is no `model` parameter.
    """
    urls: list[str] = []

    # Strategy 1: S2 homepage. Apply SSRF filtering up front so an unsafe S2
    # URL doesn't get appended and silently suppress the LLM fallback below
    # (the `if not urls:` gate would otherwise see a non-empty list).
    if s2_homepage and _is_safe_url(s2_homepage):
        urls.append(s2_homepage)
        logger.info(f"[Homepage] S2 homepage: {s2_homepage}")

    # Strategy 2: LLM URL suggestion (only if no safe URLs found yet)
    if not urls:
        prompt = HOMEPAGE_URL_PROMPT.format(name=name, affiliation=affiliation or "unknown")
        try:
            response = call_llm(prompt, model="haiku", cache=cache, backend=backend)
            result = parse_json_response(response, backend=backend)
            if result and "urls" in result:
                for url in result["urls"]:
                    if isinstance(url, str) and url.startswith("http") and url not in urls:
                        urls.append(url)
                logger.info(f"[Homepage] LLM 推荐 {len(result['urls'])} 个 URL")
        except Exception as e:
            logger.warning(f"[Homepage] LLM URL 推荐失败: {e}")

    return [u for u in urls if _is_safe_url(u)]


def extract_students_from_homepage(
    page_text: str,
    researcher_name: str,
    model: str = "sonnet",
    cache: DiskCache | None = None,
    backend: str = "claude_cli",
) -> list[StudentCandidate]:
    """Use LLM to extract student/postdoc names from homepage text."""
    if not page_text or len(page_text.strip()) < 100:
        return []

    # Truncate for LLM prompt
    text_for_prompt = page_text[:30000]

    prompt = HOMEPAGE_STUDENT_PROMPT.format(
        researcher_name=researcher_name,
        page_text=text_for_prompt,
    )

    try:
        response = call_llm(prompt, model=model, cache=cache, backend=backend)
        result = parse_json_response(response, backend=backend)
    except Exception as e:
        logger.warning(f"[Homepage] LLM 学生提取失败: {e}")
        return []

    if not result or "students" not in result:
        return []

    candidates = []
    for s in result["students"]:
        if not isinstance(s, dict):
            continue  # LLM sometimes returns bare name strings — skip, don't crash
        name = s.get("name", "").strip()
        if not name:
            continue
        status = s.get("status", "unknown")
        if status not in ("current", "graduated", "postdoc", "unknown"):
            status = "unknown"
        candidates.append(StudentCandidate(
            name=name,
            source="homepage",
            status=status,
            research_direction=s.get("research_direction", ""),
        ))

    logger.info(f"[Homepage] 从主页提取 {len(candidates)} 个学生")
    return candidates


def discover_students_from_homepage(
    name: str,
    affiliation: str,
    s2_homepage: str = "",
    homepage_url: str = "",
    model: str = "sonnet",
    cache: DiskCache | None = None,
    backend: str = "claude_cli",
) -> list[StudentCandidate]:
    """Top-level orchestrator: find URLs -> fetch -> extract -> deduplicate.

    Args:
        name: Researcher name
        affiliation: Current affiliation
        s2_homepage: Homepage URL from Semantic Scholar (if any)
        homepage_url: Explicit homepage URL from CLI --homepage flag
        model: LLM model for extraction
        cache: DiskCache instance
        backend: LLM backend
    """
    # Build URL list
    urls: list[str] = []
    if homepage_url:
        urls.append(homepage_url)

    # Discover more URLs (S2 + LLM). URL suggestion always uses haiku, so the
    # profiler's `model` is intentionally not forwarded here.
    discovered = discover_homepage_urls(
        name, affiliation, s2_homepage=s2_homepage,
        cache=cache, backend=backend,
    )
    for u in discovered:
        if u not in urls:
            urls.append(u)

    if not urls:
        logger.info(f"[Homepage] 未找到 {name} 的主页 URL")
        return []

    print(f"  [Homepage] 发现 {len(urls)} 个候选 URL")

    # Fetch and extract from each URL
    all_candidates: list[StudentCandidate] = []
    seen_names: set[str] = set()

    for url in urls:
        text = fetch_homepage(url, cache=cache)
        if not text:
            continue

        candidates = extract_students_from_homepage(
            text, name, model=model, cache=cache, backend=backend,
        )

        for c in candidates:
            name_lower = c.name.lower().strip()
            if name_lower not in seen_names:
                seen_names.add(name_lower)
                all_candidates.append(c)

    print(f"  [Homepage] 共提取 {len(all_candidates)} 个学生")
    return all_candidates
