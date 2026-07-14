"""OpenReview API client for fetching paper reviews.

Supports guest (unauthenticated) access by default.
Optional authenticated access via OPENREVIEW_USERNAME / OPENREVIEW_PASSWORD env vars.

Uses openreview-py library (pip install openreview-py).
"""

from __future__ import annotations

import difflib
import logging
import os
import re
import time
from datetime import datetime
from typing import Any

from research.apis.rate_limiter import openreview_limiter
from research.cache import DiskCache

logger = logging.getLogger("research_scout")

# Venue ID patterns for major conferences on OpenReview.
# Year-based venues use a "{year}" placeholder; year-less venues (e.g. TMLR,
# which is a continuously-running journal with no per-year conference) use a
# fixed invitation path with no placeholder.
VENUE_PATTERNS: dict[str, str] = {
    "ICLR": "ICLR.cc/{year}/Conference",
    "NeurIPS": "NeurIPS.cc/{year}/Conference",
    "ICML": "ICML.cc/{year}/Conference",
    "COLM": "COLM.cc/{year}/Conference",
    # TMLR is year-less. The pattern below is already a full invitation id, so
    # _get_venue_submissions must not append the usual "/-/Submission" suffix.
    "TMLR": "TMLR/-/Submission",
}


def _search_years(current_year: int | None = None) -> range:
    """Years to search (recent venues), derived from the current year.

    Spans the four most recent years up to and including next year, so that
    upcoming-conference venues (e.g. ICLR 2027 published in late 2026) remain
    reachable without a hardcoded sunset date.
    """
    year = current_year if current_year is not None else datetime.now().year
    return range(year - 2, year + 2)


# Backward-compatible default range computed at import time.
SEARCH_YEARS = _search_years()

# OpenReview API base URL
API_V2_URL = "https://api2.openreview.net"


class OpenReviewClient:
    """OpenReview API client with guest/authenticated access and caching."""

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        cache: DiskCache | None = None,
    ):
        try:
            import openreview
        except ImportError:
            raise ImportError(
                "openreview-py 未安装。请运行: pip install openreview-py"
            )

        self._or = openreview

        # Auth: env vars > constructor args > guest
        self._username = username or os.environ.get("OPENREVIEW_USERNAME", "")
        self._password = password or os.environ.get("OPENREVIEW_PASSWORD", "")

        self._client = None
        self._cache = cache
        self._init_client()

    def _init_client(self) -> None:
        """Initialize OpenReview API v2 client."""
        try:
            if self._username and self._password:
                self._client = self._or.api.OpenReviewClient(
                    baseurl=API_V2_URL,
                    username=self._username,
                    password=self._password,
                )
                logger.info("[OpenReview] 已认证登录: %s", self._username)
            else:
                self._client = self._or.api.OpenReviewClient(
                    baseurl=API_V2_URL,
                )
                logger.info("[OpenReview] Guest 模式 (无认证)")
        except Exception as e:
            logger.warning("[OpenReview] 客户端初始化失败: %s", e)
            self._client = None

    def search_submission(
        self,
        title: str,
        authors: list[str] | None = None,
        venue_hint: str | None = None,
    ) -> dict[str, Any] | None:
        """Search OpenReview for a submission matching the given title.

        Uses fuzzy title matching (threshold 0.85).
        Returns submission dict with forum ID, or None if not found.
        """
        if not self._client:
            return None

        # Determine which venues to search
        venues_to_search = self._resolve_venues(venue_hint)

        for venue_id in venues_to_search:
            # Check cache
            cache_key = f"or_submissions:{venue_id}"
            submissions = self._get_venue_submissions(venue_id, cache_key)
            if not submissions:
                continue

            # Fuzzy match
            match = self._fuzzy_match_title(title, submissions)
            if match:
                return match

        return None

    def _resolve_venues(self, venue_hint: str | None) -> list[str]:
        """Resolve venue IDs to search based on hint."""
        venues = []
        # Derive the year range from the current year at call time so the set of
        # reachable venues advances automatically (no hardcoded sunset).
        search_years = _search_years()

        if venue_hint:
            # Try to match hint to known patterns
            hint_upper = venue_hint.upper()
            for conf, pattern in VENUE_PATTERNS.items():
                if conf.upper() in hint_upper:
                    if "{year}" not in pattern:
                        # Year-less venue (e.g. TMLR): pattern is already complete.
                        venues.append(pattern)
                    else:
                        # Extract year from hint if present
                        year_match = re.search(r'20\d{2}', venue_hint)
                        if year_match:
                            venues.append(pattern.format(year=year_match.group()))
                        else:
                            for year in search_years:
                                venues.append(pattern.format(year=year))
                    break

        if not venues:
            # Search all recent venues
            for conf, pattern in VENUE_PATTERNS.items():
                if "{year}" not in pattern:
                    venues.append(pattern)
                    continue
                for year in search_years:
                    venues.append(pattern.format(year=year))

        return venues

    def _get_venue_submissions(
        self, venue_id: str, cache_key: str
    ) -> list[dict[str, Any]]:
        """Get all submissions for a venue, with caching."""
        # Check cache (7-day TTL)
        if self._cache:
            cached = self._cache.get("api/openreview", cache_key, ttl_seconds=7 * 86400)
            if cached is not None:
                return cached

        # NOTE: the rate limiter is acquired once per get_all_notes() call, not
        # once per underlying HTTP page. get_all_notes() may paginate internally
        # (issuing several HTTP requests), so the effective request rate can
        # briefly exceed the limiter's nominal rate for paginated venues.
        openreview_limiter.acquire()
        try:
            # Year-less venue patterns (e.g. "TMLR/-/Submission") are already a
            # complete invitation id; only year-based venue ids need the suffix.
            if venue_id.endswith("/-/Submission"):
                invitation = venue_id
            else:
                invitation = f"{venue_id}/-/Submission"
            notes = self._client.get_all_notes(invitation=invitation)
            submissions = []
            for note in notes:
                content = note.content or {}
                sub = {
                    "forum_id": note.forum,
                    "title": _extract_value(content.get("title", {})),
                    "authors": _extract_value(content.get("authors", {})) or [],
                    "venue_id": venue_id,
                }
                if sub["title"]:
                    submissions.append(sub)

            if self._cache and submissions:
                self._cache.put("api/openreview", cache_key, submissions)

            logger.debug("[OpenReview] %s: %d submissions", venue_id, len(submissions))
            return submissions
        except Exception as e:
            logger.debug("[OpenReview] 获取 %s 失败: %s", venue_id, e)
            return []

    def _fuzzy_match_title(
        self, query_title: str, submissions: list[dict]
    ) -> dict[str, Any] | None:
        """Fuzzy match a query title against cached submissions."""
        normalized_query = _normalize_title(query_title)

        best_match = None
        best_ratio = 0.0

        for sub in submissions:
            candidate = _normalize_title(sub.get("title", ""))
            ratio = difflib.SequenceMatcher(None, normalized_query, candidate).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = sub

        if best_match and best_ratio >= 0.85:
            logger.info(
                "[OpenReview] 匹配成功 (%.2f): %s",
                best_ratio,
                best_match.get("title", "")[:60],
            )
            return best_match

        return None

    def fetch_reviews(self, forum_id: str) -> list[dict[str, Any]]:
        """Fetch all reviews for a submission by forum ID.

        Returns list of review dicts with rating, confidence, strengths, etc.
        """
        if not self._client:
            return []

        # Check cache
        cache_key = f"or_reviews:{forum_id}"
        if self._cache:
            cached = self._cache.get("api/openreview", cache_key, ttl_seconds=7 * 86400)
            if cached is not None:
                return cached

        openreview_limiter.acquire()
        try:
            # Get all replies to the forum (includes reviews, meta-reviews, etc.)
            notes = self._client.get_all_notes(forum=forum_id)
            reviews = []
            for note in notes:
                content = note.content or {}
                # Identify reviews by presence of rating field
                rating = _extract_value(content.get("rating", {}))
                if not rating:
                    # Try alternative field names
                    rating = _extract_value(content.get("recommendation", {}))
                if not rating:
                    continue

                review = {
                    "rating": rating,
                    "confidence": _extract_value(content.get("confidence", {})),
                    "soundness": _extract_value(content.get("soundness", {})),
                    "presentation": _extract_value(content.get("presentation", {})),
                    "contribution": _extract_value(content.get("contribution", {})),
                    "strengths": _extract_value(content.get("strengths", {})),
                    "weaknesses": _extract_value(content.get("weaknesses", {})),
                    "questions": _extract_value(content.get("questions", {})),
                    "suggestions": _extract_value(
                        content.get("suggestions", content.get("suggestions_for_improvement", {}))
                    ),
                    "summary": _extract_value(content.get("summary", {})),
                }
                # Check if this is a meta-review. API v2 notes expose
                # `invitations` (a list); fall back to the v1 `invitation`
                # (a single string) for compatibility.
                invitations = getattr(note, "invitations", None)
                if not invitations:
                    single = getattr(note, "invitation", "") or ""
                    invitations = [single] if single else []
                if any(
                    "Meta_Review" in inv or "meta_review" in inv.lower()
                    for inv in invitations
                ):
                    review["is_meta_review"] = True
                reviews.append(review)

            if self._cache:
                self._cache.put("api/openreview", cache_key, reviews)

            return reviews
        except Exception as e:
            logger.warning("[OpenReview] 获取 reviews 失败 %s: %s", forum_id, e)
            return []

    def fetch_paper_reviews(self, paper: dict) -> dict[str, Any] | None:
        """High-level: search for paper on OpenReview and fetch its reviews.

        Returns dict with 'submission' and 'reviews' keys, or None if not found.
        """
        title = paper.get("title", "")
        if not title:
            return None

        authors = paper.get("authors", [])
        venue = paper.get("venue", "") or paper.get("comment", "")

        submission = self.search_submission(title, authors=authors, venue_hint=venue)
        if not submission:
            return None

        forum_id = submission.get("forum_id", "")
        if not forum_id:
            return None

        reviews = self.fetch_reviews(forum_id)
        return {
            "submission": submission,
            "reviews": reviews,
        }


# ─── Helpers ───────────────────────────────────────────────────────

def _normalize_title(title: str) -> str:
    """Normalize paper title for matching: lowercase, strip punctuation, collapse whitespace."""
    title = title.lower().strip()
    title = re.sub(r'[^\w\s]', '', title)
    title = re.sub(r'\s+', ' ', title)
    return title


def _extract_value(field: Any) -> Any:
    """Extract value from OpenReview content field (may be dict with 'value' key or plain)."""
    if isinstance(field, dict):
        return field.get("value", "")
    return field or ""
