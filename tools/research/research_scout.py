#!/usr/bin/env python3
"""Research Paper Scout — DEPRECATION SHIM.

This file is a thin compatibility shim. The actual implementation has moved to
the `research.scout` package. Please update your imports:

    # Old (deprecated):
    from research_scout import load_all_projects
    python tools/research/research_scout.py report ...

    # New (recommended):
    from research.scout.project import load_all_projects
    python -m research.scout report ...

This shim will be removed in a future version.
"""

import warnings as _warnings

_warnings.warn(
    "research_scout.py is deprecated. Use 'python -m research.scout' or import from research.scout.* instead.",
    DeprecationWarning,
    stacklevel=2,
)

# ─── Re-export all public symbols for backward compatibility ────────

# Config
from research.scout.config import (  # noqa: F401
    load_scout_config as _load_scout_config,
    setup_logging as _setup_logging,
)

# Initialize logging for backward compat (original ran at import time)
logger = _setup_logging()

# Project CRUD
from research.scout.project import (  # noqa: F401
    create_project,
    create_project_from_overview,
    load_project,
    save_project,
    load_all_projects,
)

# Search
from research.scout.search import (  # noqa: F401
    build_arxiv_query,
    search_arxiv,
    search_arxiv_conference,
    search_arxiv_author,
    search_biorxiv,
    search_pubmed,
    paper_id as _paper_id,
    paper_url as _paper_url,
    load_known_paper_ids as _load_known_paper_ids,
    load_search_cache as _load_search_cache,
    save_search_cache as _save_search_cache,
)

# Evaluate
from research.scout.evaluate import (  # noqa: F401
    call_scout_llm as _call_llm,
    evaluate_papers_for_project,
    suggest_directions,
    analyze_citations as _analyze_citations,
)

# Report
from research.scout.report import (  # noqa: F401
    generate_daily_report,
    generate_report_markdown,
    save_report,
    generate_hugo_post,
    append_literature_note,
)

# CLI entry point
from research.scout.cli import main


if __name__ == "__main__":
    main()
