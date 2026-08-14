"""Infer student-advisor relationships from co-authorship patterns."""

from __future__ import annotations

import logging
from typing import Any

from research.models import StudentCandidate

logger = logging.getLogger(__name__)


def score_student_candidates(
    coauthor_data: list[dict[str, Any]],
    max_candidates: int = 10,
    weights: dict[str, float] | None = None,
    threshold: float | None = None,
) -> list[StudentCandidate]:
    """Score co-authors on likelihood of being students.

    Signals:
    - First-author papers with advisor as last author (strongest signal)
    - Collaboration concentrated in 3-7 year window (PhD period)
    - Minimum 2 co-authored papers
    - Collaboration span suggests mentorship timeline

    ``threshold`` and ``weights`` default to ``research.scoring.student_threshold``
    (0.4) and ``research.scoring.student_weights`` when omitted.
    """
    from research.config import (
        DEFAULT_STUDENT_THRESHOLD,
        DEFAULT_STUDENT_WEIGHTS,
        scoring_config,
    )

    scoring = scoring_config()
    if threshold is None:
        raw = scoring.get("student_threshold", DEFAULT_STUDENT_THRESHOLD)
        threshold = float(raw) if raw is not None else DEFAULT_STUDENT_THRESHOLD
    w = dict(DEFAULT_STUDENT_WEIGHTS)
    cfg_w = scoring.get("student_weights")
    if isinstance(cfg_w, dict):
        w.update(cfg_w)
    if weights:
        w.update(weights)

    candidates = []

    for ca in coauthor_data:
        total = ca.get("total_collabs", 0)
        if total < 2:
            continue

        first_with_last = ca.get("first_author_with_advisor_last", 0)
        span = ca.get("collab_span", 0)
        start = ca.get("collab_start", 0)
        end = ca.get("collab_end", 0)

        # 1. First-author signal
        if total > 0 and first_with_last > 0:
            first_ratio = first_with_last / total
            first_score = min(1.0, first_ratio * 2)  # 50%+ first-author → full score
            # Bonus for multiple first-author papers
            first_score = min(1.0, first_score + 0.1 * min(first_with_last, 5))
        else:
            first_score = 0.0

        # 2. Time concentration (weight: 0.25)
        # PhD is typically 3-6 years
        if span >= 3 and span <= 7:
            time_score = 1.0
        elif span >= 2 and span <= 10:
            time_score = 0.6
        elif span >= 1:
            time_score = 0.3
        else:
            time_score = 0.1

        # 3. Collaboration frequency (weight: 0.20)
        freq_score = min(1.0, total / 8.0)  # 8+ papers → full score

        # 4. Recency (weight: 0.15) — more recent collaborations are more interesting
        import datetime
        current_year = datetime.datetime.now().year
        if end and end >= current_year - 5:
            recency_score = 1.0
        elif end and end >= current_year - 10:
            recency_score = 0.6
        else:
            recency_score = 0.3

        # Composite score
        score = (
            first_score * w["first_author"] +
            time_score * w["time_concentration"] +
            freq_score * w["frequency"] +
            recency_score * w["recency"]
        )

        if score < threshold:
            continue

        candidates.append(StudentCandidate(
            name=ca.get("name", ""),
            coauthor_count=total,
            first_author_count=first_with_last,
            collab_start_year=start,
            collab_end_year=end,
            relationship_score=round(score, 3),
        ))

    # Sort by score descending
    candidates.sort(key=lambda x: x.relationship_score, reverse=True)
    return candidates[:max_candidates]
