"""Scoring algorithms for researcher tier classification."""

from __future__ import annotations

import math

from research.models import ResearcherMetrics, ResearcherTier


def compute_tier_score(
    metrics: ResearcherMetrics,
    weights: dict[str, float] | None = None,
) -> float:
    """Compute a 0-100 score based on weighted bibliometric dimensions.

    Default weights (override via `weights` dict):
        h_index:         25%
        total_citations:  20%
        recent_citations: 20%
        top_venue_ratio:  20%
        career_stage:     15%
    """
    w = {
        "h_index": 25,
        "total_citations": 20,
        "recent_citations": 20,
        "top_venue_ratio": 20,
        "career_stage": 15,
    }
    if weights:
        w.update(weights)

    # h-index score (0-1)
    h = metrics.h_index
    if h >= 60:
        h_score = 1.0
    elif h >= 40:
        h_score = 0.8
    elif h >= 25:
        h_score = 0.6
    elif h >= 15:
        h_score = 0.4
    elif h >= 8:
        h_score = 0.2
    else:
        h_score = h / 8.0 * 0.2

    # Total citations (log scale, 0-1)
    if metrics.total_citations > 0:
        # log10(100000) ≈ 5 → score 1.0
        cite_score = min(1.0, math.log10(max(1, metrics.total_citations)) / 5.0)
    else:
        cite_score = 0.0

    # Recent 5yr citations (log scale, 0-1)
    if metrics.recent_citations_5yr > 0:
        # log10(50000) ≈ 4.7 → score 1.0
        recent_score = min(1.0, math.log10(max(1, metrics.recent_citations_5yr)) / 4.7)
    else:
        recent_score = 0.0

    # Top venue ratio (0-1)
    if metrics.paper_count > 0:
        ratio = metrics.top_venue_count / metrics.paper_count
        venue_score = min(1.0, ratio * 3.0)  # 33%+ top venues → full score
    else:
        venue_score = 0.0

    # Career development (0-1)
    import datetime
    current_year = datetime.datetime.now().year
    # Clamp to 0 so future-dated first_paper_year doesn't yield negative years
    career_years = max(0, current_year - metrics.first_paper_year) if metrics.first_paper_year else 0
    if career_years >= 15:
        career_score = 1.0
    elif career_years >= 10:
        career_score = 0.8
    elif career_years >= 6:
        career_score = 0.6
    elif career_years >= 3:
        career_score = 0.4
    else:
        career_score = career_years / 3.0 * 0.4

    # Weighted sum
    score = (
        h_score * w["h_index"] +
        cite_score * w["total_citations"] +
        recent_score * w["recent_citations"] +
        venue_score * w["top_venue_ratio"] +
        career_score * w["career_stage"]
    )
    return round(score, 1)


def classify_tier(
    score: float,
    thresholds: dict[str, float] | None = None,
) -> ResearcherTier:
    """Classify researcher tier based on score.

    Default thresholds: ESTABLISHED_LEADER >= 75, RISING_STAR >= 50,
    ACTIVE_RESEARCHER >= 30, EARLY_CAREER < 30.
    Override via `thresholds` dict with keys: leader, rising, active.
    """
    t = {"leader": 75, "rising": 50, "active": 30}
    if thresholds:
        t.update(thresholds)

    if score >= t["leader"]:
        return ResearcherTier.ESTABLISHED_LEADER
    elif score >= t["rising"]:
        return ResearcherTier.RISING_STAR
    elif score >= t["active"]:
        return ResearcherTier.ACTIVE_RESEARCHER
    else:
        return ResearcherTier.EARLY_CAREER
