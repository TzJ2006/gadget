"""Data models for researcher analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


@dataclass
class Paper:
    """A single research paper."""
    arxiv_id: str = ""
    title: str = ""
    abstract: str = ""
    authors: list[str] = field(default_factory=list)
    published: str = ""  # ISO date string
    categories: list[str] = field(default_factory=list)
    pdf_url: str = ""
    citation_count: int = 0
    venue: str = ""
    full_text: str = ""  # Only populated in detailed mode
    award: str = ""  # "best_paper", "highlight", "spotlight", "oral", or ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "arxiv_id": self.arxiv_id,
            "title": self.title,
            "abstract": self.abstract,
            "authors": self.authors,
            "published": self.published,
            "categories": self.categories,
            "pdf_url": self.pdf_url,
            "citation_count": self.citation_count,
            "venue": self.venue,
            "full_text": self.full_text if self.full_text else None,
            "award": self.award if self.award else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Paper:
        return cls(
            arxiv_id=d.get("arxiv_id", ""),
            title=d.get("title", ""),
            abstract=d.get("abstract", ""),
            authors=d.get("authors", []),
            published=d.get("published", ""),
            categories=d.get("categories", []),
            pdf_url=d.get("pdf_url", ""),
            citation_count=d.get("citation_count", 0),
            venue=d.get("venue", ""),
            full_text=d.get("full_text") or "",
            award=d.get("award") or "",
        )


@dataclass
class ResearcherMetrics:
    """Bibliometric data for a researcher."""
    h_index: int = 0
    total_citations: int = 0
    recent_citations_5yr: int = 0
    paper_count: int = 0
    top_venue_count: int = 0
    current_affiliation: str = ""
    first_paper_year: int = 0
    latest_paper_year: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "h_index": self.h_index,
            "total_citations": self.total_citations,
            "recent_citations_5yr": self.recent_citations_5yr,
            "paper_count": self.paper_count,
            "top_venue_count": self.top_venue_count,
            "current_affiliation": self.current_affiliation,
            "first_paper_year": self.first_paper_year,
            "latest_paper_year": self.latest_paper_year,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ResearcherMetrics:
        return cls(**{k: d.get(k, v) for k, v in cls.__dataclass_fields__.items()
                      if k in d})


class ResearcherTier(Enum):
    """Classification tier for researchers."""
    ESTABLISHED_LEADER = "established_leader"
    RISING_STAR = "rising_star"
    ACTIVE_RESEARCHER = "active_researcher"
    EARLY_CAREER = "early_career"

    @property
    def label_cn(self) -> str:
        return {
            "established_leader": "领域大佬",
            "rising_star": "新星",
            "active_researcher": "活跃研究者",
            "early_career": "早期研究者",
        }[self.value]

    @property
    def label_en(self) -> str:
        return {
            "established_leader": "Established Leader",
            "rising_star": "Rising Star",
            "active_researcher": "Active Researcher",
            "early_career": "Early Career",
        }[self.value]


@dataclass
class StudentCandidate:
    """A potential student inferred from co-authorship patterns or homepage data."""
    name: str = ""
    coauthor_count: int = 0
    first_author_count: int = 0  # Papers where they are first author with advisor
    collab_start_year: int = 0
    collab_end_year: int = 0
    independent_papers_after: int = 0  # Papers without advisor after collab period
    relationship_score: float = 0.0  # 0-1 confidence
    research_direction: str = ""
    source: str = ""    # "homepage", "coauthorship", "both"
    status: str = ""    # "current", "graduated", "postdoc", "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "coauthor_count": self.coauthor_count,
            "first_author_count": self.first_author_count,
            "collab_start_year": self.collab_start_year,
            "collab_end_year": self.collab_end_year,
            "independent_papers_after": self.independent_papers_after,
            "relationship_score": self.relationship_score,
            "research_direction": self.research_direction,
            "source": self.source,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StudentCandidate:
        return cls(**{k: d.get(k, v) for k, v in cls.__dataclass_fields__.items()
                      if k in d})


@dataclass
class ResearcherProfile:
    """Complete analysis profile for a researcher."""
    name: str = ""
    metrics: ResearcherMetrics = field(default_factory=ResearcherMetrics)
    papers: list[Paper] = field(default_factory=list)
    analysis: dict[str, Any] = field(default_factory=dict)  # LLM-generated
    inferred_students: list[StudentCandidate] = field(default_factory=list)
    tier: ResearcherTier = ResearcherTier.EARLY_CAREER
    tier_score: float = 0.0
    s2_author_id: str = ""  # Semantic Scholar author ID
    mode: str = "fast"  # "fast" or "detailed"
    fetched_at: str = ""  # ISO datetime

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "metrics": self.metrics.to_dict(),
            "papers": [p.to_dict() for p in self.papers],
            "analysis": self.analysis,
            "inferred_students": [s.to_dict() for s in self.inferred_students],
            "s2_author_id": self.s2_author_id,
            "tier": self.tier.value,
            "tier_score": self.tier_score,
            "mode": self.mode,
            "fetched_at": self.fetched_at,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ResearcherProfile:
        return cls(
            name=d.get("name", ""),
            metrics=ResearcherMetrics.from_dict(d.get("metrics", {})),
            papers=[Paper.from_dict(p) for p in d.get("papers", [])],
            analysis=d.get("analysis", {}),
            inferred_students=[StudentCandidate.from_dict(s) for s in d.get("inferred_students", [])],
            s2_author_id=d.get("s2_author_id", ""),
            tier=ResearcherTier(d.get("tier", "early_career")),
            tier_score=d.get("tier_score", 0.0),
            mode=d.get("mode", "fast"),
            fetched_at=d.get("fetched_at", ""),
        )
