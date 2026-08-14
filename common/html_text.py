"""Tiny stdlib HTML → visible text (optional http(s) links)."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Iterable

DEFAULT_SKIP_TAGS = frozenset({
    "script", "style", "nav", "header", "footer",
    "svg", "noscript", "figure", "figcaption",
})
DEFAULT_RECOVERY_TAGS = frozenset({"body", "main"})
DEFAULT_BLOCK_TAGS = frozenset({
    "p", "div", "h1", "h2", "h3", "h4", "h5", "li", "tr", "br", "section",
})

_MULTI_NEWLINE = re.compile(r"\n{3,}")


class HTMLTextExtractor(HTMLParser):
    """Strip tags to text; optionally collect absolute http(s) links.

    Unclosed skip tags are cleared when a recovery landmark (body/main) is
    seen, so a missing </nav> cannot swallow the rest of the document.
    """

    def __init__(
        self,
        *,
        skip_tags: Iterable[str] | None = None,
        recovery_tags: Iterable[str] | None = None,
        block_tags: Iterable[str] | None = None,
        collect_links: bool = False,
    ) -> None:
        super().__init__()
        self.skip_tags = (
            frozenset(skip_tags) if skip_tags is not None else DEFAULT_SKIP_TAGS
        )
        self.recovery_tags = (
            frozenset(recovery_tags) if recovery_tags is not None
            else DEFAULT_RECOVERY_TAGS
        )
        self.block_tags = (
            frozenset(block_tags) if block_tags is not None else DEFAULT_BLOCK_TAGS
        )
        self.collect_links = collect_links
        self._text_parts: list[str] = []
        self._links: list[str] = []
        self._skip_stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.recovery_tags:
            self._skip_stack.clear()
        if tag in self.skip_tags:
            self._skip_stack.append(tag)
            return
        if self._skip_stack:
            return
        if self.collect_links and tag == "a":
            href = dict(attrs).get("href", "")
            if href.startswith("http"):
                self._links.append(href)

    def handle_endtag(self, tag):
        if tag in self.skip_tags and tag in self._skip_stack:
            for i in range(len(self._skip_stack) - 1, -1, -1):
                if self._skip_stack[i] == tag:
                    del self._skip_stack[i]
                    break
        if tag in self.block_tags:
            self._text_parts.append("\n")

    def handle_data(self, data):
        if not self._skip_stack:
            self._text_parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._text_parts)
        return _MULTI_NEWLINE.sub("\n\n", text).strip()

    def get_links(self) -> list[str]:
        return self._links


def html_to_text(
    html: str,
    *,
    skip_tags: Iterable[str] | None = None,
    recovery_tags: Iterable[str] | None = None,
    block_tags: Iterable[str] | None = None,
) -> str:
    """Parse *html* and return visible text."""
    extractor = HTMLTextExtractor(
        skip_tags=skip_tags,
        recovery_tags=recovery_tags,
        block_tags=block_tags,
    )
    extractor.feed(html)
    extractor.close()
    return extractor.get_text()
