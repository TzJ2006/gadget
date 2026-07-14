# CLAUDE.md

> **Workflow**: This module follows the agentic protocol in [`AGENTS.md`](AGENTS.md) — AI Dev Companion pipeline; plans live in `../../docs/ecl/*.yaml`.

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Unified research toolkit with a single CLI entry point (`research_scout.py`):

1. **Research Scout** (`research_scout.py`, backward-compat shim → modular `scout/` package) — Paper discovery and evaluation. Searches arXiv, bioRxiv, PubMed; three-stage LLM pipeline (screening → deep analysis → citation impact); generates reports; deploys to Hugo blog. See `TUTORIAL.md` for user-facing docs (中文).

2. **Researcher Profiler** (modular package, also accessible via `research_scout.py profile`) — Academic researcher analysis. Fetches papers from ArXiv + Semantic Scholar, runs LLM trajectory analysis, computes tier scores, discovers student-advisor relationships via homepage extraction + co-authorship patterns.

3. **Citation Graph** (integrated into Research Scout) — Forward citations (who cites this paper) and backward references (what this paper cites) via Semantic Scholar API. LLM-based influence analysis for popular papers.

## Usage

### Research Scout (paper discovery)

```bash
# All commands run from repo root
python tools/research/research_scout.py config --init                              # First-time config
python tools/research/research_scout.py init my-project --title "Title" \
    --keywords "kw1" "kw2" --categories "cs.RO" "cs.LG"                    # Create project
python tools/research/research_scout.py init my-project --from-overview path/to/overview.md  # Create from existing overview
python tools/research/research_scout.py list                                       # List projects
python tools/research/research_scout.py search --project my-project               # Search (default: arXiv)
python tools/research/research_scout.py search --source arxiv biorxiv             # Multi-source search
python tools/research/research_scout.py search --conference "CVPR 2025"           # Conference papers (arXiv only)
python tools/research/research_scout.py search --author "Pieter Abbeel"           # Author search
python tools/research/research_scout.py report --project my-project               # Full pipeline: search + eval + report
python tools/research/research_scout.py report --api anthropic                    # Use Anthropic API
python tools/research/research_scout.py report --language en                      # English output (default: zh)
python tools/research/research_scout.py report --no-cache                         # Bypass caches
python tools/research/research_scout.py report --project my-project --deploy      # Full pipeline + deploy to Hugo
python tools/research/research_scout.py report --project my-project --insight     # + Stage 4+5: insight analysis + OpenReview
python tools/research/research_scout.py report --insight --insight-top-n 5        # Insight on top 5 papers
python tools/research/research_scout.py deploy                                    # Deploy reports to Hugo

# Natural language search (ask command)
python tools/research/research_scout.py ask "找 Pieter Abbeel 最近的机器人操作论文"    # Author + topic
python tools/research/research_scout.py ask "ICRA 2025 的灵巧手操作"                  # Conference search
python tools/research/research_scout.py ask "BMJ/Lancet 上最近的 AI 诊断论文"         # Journal search (auto PubMed)
python tools/research/research_scout.py ask "sim-to-real transfer 在 legged robot 上的进展"  # Topic search
python tools/research/research_scout.py ask "找最近的 diffusion policy 机器人控制论文" --deploy  # + deploy
```

### Researcher Profiler (via unified CLI or standalone)

```bash
# Unified CLI (recommended)
python tools/research/research_scout.py profile "Sergey Levine"                    # Analyze researcher (fast mode)
python tools/research/research_scout.py profile "Sergey Levine" --mode detailed    # Detailed mode (downloads full texts)
python tools/research/research_scout.py profile "Sergey Levine" --depth 1          # Recursive: also analyze discovered students
python tools/research/research_scout.py profile --from-file names.txt              # Batch: one name per line
python tools/research/research_scout.py profile "Name" --model opus --no-cache     # Model override, skip cache
python tools/research/research_scout.py profile "Name" --api anthropic             # Use Anthropic API backend
python tools/research/research_scout.py profile "Name" --homepage "https://..."   # Hint: researcher homepage URL
python tools/research/research_scout.py profile "Name" --affiliation "UC Berkeley" # Hint: affiliation for disambiguation
python tools/research/research_scout.py profile "Name" --paper "2301.12597"        # Hint: paper arXiv ID/DOI/title
python tools/research/research_scout.py profile "Name" --author-id "S2_ID"         # Direct Semantic Scholar author ID
python tools/research/research_scout.py profile "Name" --deploy                    # Analyze + deploy to Hugo

# Standalone (also still works, via cli.py → analysis.py)
python -m research analyze "Sergey Levine"                    # Analyze researcher (fast mode)
python -m research analyze "Sergey Levine" --api anthropic    # Backend select (ollama/claude_cli/anthropic/openai)
python -m research show "Sergey Levine"                       # Display cached profile
python -m research list                                       # List all analyzed researchers
python -m research config --init                              # Interactive config setup
```

### Citation Graph Analysis

```bash
python tools/research/research_scout.py citations 2301.12597                       # Citation graph for arXiv paper
python tools/research/research_scout.py citations 2301.12597 --top-n 20           # Show top 20 citations
python tools/research/research_scout.py citations 10.1038/s41586-023-06221-2      # By DOI
python tools/research/research_scout.py citations 2301.12597 --api anthropic      # Use Anthropic for analysis
python tools/research/research_scout.py citations 2301.12597 --no-cache           # Bypass cache
```

## Architecture: Research Scout

Modular `scout/` package:

- **`scout/config.py`**: Path constants, tunable defaults, config loading, logging
- **`scout/project.py`**: Project CRUD (`create_project`, `create_project_from_overview`, `create_project_from_query`, `load_project`, `save_project`, `load_all_projects`)
- **`scout/search.py`**: Multi-source search (arXiv + bioRxiv + PubMed), search cache, paper ID helpers
- **`scout/evaluate.py`**: LLM backend (`call_scout_llm`), three-stage evaluation pipeline, `suggest_directions()`, `analyze_citations()`
- **`scout/insight.py`**: Stage 4+5: full-text insight analysis (`analyze_paper_insight`), OpenReview review consensus (`analyze_review_consensus`), writing guide synthesis (`synthesize_writing_guide`), `run_insight_analysis()` orchestrator
- **`scout/report.py`**: Report generation + Hugo deployment + `append_literature_note()` + `render_insight_details()`, `render_review_summary()`, `generate_writing_guide_section()`
- **`scout/prompts.py`**: All LLM prompt templates (screening, deep eval, direction suggestion, overview extraction, ask intent, insight analysis, review consensus, writing guide)
- **`scout/ask.py`**: Natural language `ask` command: `parse_ask_intent()`, `validate_ask_plan()`, `route_search()`
- **`scout/cli.py`**: CLI commands (`cmd_ask`, `cmd_report`, `cmd_search`, `cmd_init`, etc.) + `run_evaluation_pipeline()`, `finalize_report()`

### Five-Stage Evaluation Pipeline

```
Papers from arXiv / bioRxiv / PubMed
    |
Stage 1: Quick Screening (_screen_papers / _screen_papers_chunked)
    |--- ALL papers get: motivation, innovation_point, paper_type, institution
    |--- Classification: "high" or "low" relevance
    |
    +--- Low → 文献阅读记录 (collapsed in report)
    |
    +--- High (capped at max_high_relevance=20)
            |
            Stage 2: Deep Analysis (_deep_evaluate_papers)
                |--- Reads project overview.md for context
                |--- 3 highlights per paper; relevance/novelty/inspiration scores (1-5)
                |--- composite_score = 0.4*relevance + 0.3*inspiration + 0.3*novelty
                |--- Sort: composite_score desc, citation_count as tiebreaker
                |
                Stage 3: Citation Impact (_analyze_citations) — always on, top 5 papers
                    |--- Resolves arXiv ID → S2 paper ID via get_paper_by_id()
                    |--- Forward citations (top 20 by citation count)
                    |--- Backward references (top 20)
                    |--- LLM: "Why is this paper popular? What follow-up directions?"
                    |--- Attaches citation_analysis dict to paper
                |
                → suggest_directions() proposes new research directions
                → append_literature_note() updates overview.md
                |
                [if --insight] Stage 4: Insight Analysis (top N papers, default 3)
                    |--- Downloads full text (HTML first, PDF fallback via arxiv_client)
                    |--- Truncates to MAX_FULLTEXT_CHARS (40K)
                    |--- LLM: writing_structure + publishability + knowledge_extraction
                    |--- Non-arXiv: bioRxiv attempts full text, PubMed degrades to abstract
                    |--- Abstract-only papers use reduced INSIGHT_ABSTRACT_PROMPT
                    |--- Attaches insight_analysis dict to paper
                    |
                [if --insight] Stage 5: OpenReview Reviews (same top N papers)
                    |--- OpenReviewClient: guest API default, env var auth optional
                    |--- Fuzzy title matching (threshold 0.85) to find submission
                    |--- Fetches reviews: rating, confidence, strengths, weaknesses
                    |--- LLM consensus analysis (0/1/2/3+ reviewer tiers)
                    |--- Attaches review_analysis dict to paper
                    |
                    → synthesize_writing_guide() generates cross-paper writing guide
```

Entry point: `evaluate_papers_for_project()` → `{"high_relevance": [...], "low_relevance": [...], "screening_stats": {...}}`
With `--insight`: `run_insight_analysis()` adds `insight_analysis`, `review_analysis` to papers + returns `writing_guide`

### Citation Graph API (`apis/semantic_scholar.py`)

- `get_paper_by_id(paper_id)` — Resolves arXiv ID or DOI to S2 paper record
- `get_paper_citations(s2_id, limit)` — Forward citations sorted by citation count
- `get_paper_references(s2_id, limit)` — Backward references sorted by citation count

### OpenReview API (`apis/openreview_client.py`)

- `OpenReviewClient(username, password)` — Guest API by default; optional env var auth (`OPENREVIEW_USERNAME`, `OPENREVIEW_PASSWORD`)
- `search_submission(title, authors, venue_hint)` — Fuzzy title matching (threshold 0.85) across ICLR/NeurIPS/ICML venues
- `fetch_reviews(forum_id)` — All reviews for a submission (rating, confidence, strengths, weaknesses, questions)
- `fetch_paper_reviews(paper_dict)` — High-level: search + fetch reviews for a paper dict
- Rate limiting: 2 req/s via `openreview_limiter`
- Caching: DiskCache namespace `api/openreview/`, 7-day TTL
- **Not on OpenReview**: AAAI, CVPR, ICCV, ECCV (these use different review systems)

## Architecture: Researcher Profiler

Modular package with `__main__.py` entry point:

```
cli.py          → argparse (analyze, show, list, config)
analysis.py     → Main orchestrator: BFS over researchers, calls all modules
  |
  +→ apis/arxiv_client.py     → ArXiv author search + full-text download (HTML first, PDF fallback via PyMuPDF)
  +→ apis/semantic_scholar.py → S2 author metrics, paper data, co-authorship analysis
  +→ apis/rate_limiter.py     → Token-bucket rate limiter (ArXiv 1/3s, S2 10/s, Web 1/2s, OpenReview 2/s)
  |
  +→ scoring.py               → Weighted bibliometric scoring + tier classification
  +→ student_discovery.py     → Student-advisor inference from co-authorship patterns
  +→ homepage_discovery.py    → Student extraction from researcher homepages (URL discovery + HTML parsing + LLM)
  +→ llm.py                   → Multi-backend LLM wrapper (ollama/claude_cli/anthropic/openai), JSON parse with escalating LLM repair via common.json_utils
  +→ prompts.py               → LLM prompt templates (trajectory, awards, students, citation impact, homepage URL/student extraction)
  +→ output.py                → JSON profile persistence + Markdown report rendering + Hugo deployment
  |
models.py       → Dataclasses: Paper, ResearcherMetrics, ResearcherTier, StudentCandidate, ResearcherProfile
cache.py        → Re-export shim for common.cache.DiskCache
config.py       → Config at ~/.config/research/config.json
```

### Researcher Analysis Pipeline

`analyze_researcher()` in `analysis.py` runs 6 steps per researcher:

1. **ArXiv fetch** — `search_papers_by_author()` (up to 100 papers)
2. **Semantic Scholar fetch** — author metrics (h-index, citations) + all papers with citation counts
3. **Award identification** — LLM identifies Best Paper/Spotlight/Oral awards
4. **Full-text download** (detailed mode only) — HTML first, PDF fallback
5. **LLM trajectory analysis** — generates trajectory_summary, breakthroughs, research_themes, methodology_evolution
6. **Tier scoring** — weighted: h-index 25%, total citations 20%, recent citations 20%, top-venue ratio 20%, career stage 15%

Tiers: `ESTABLISHED_LEADER` (≥75), `RISING_STAR` (≥50), `ACTIVE_RESEARCHER` (≥30), `EARLY_CAREER` (<30)

### Student Discovery

`run_analysis()` uses BFS: if `depth > 0`, discovered students are enqueued for analysis.

Four-phase pipeline in `discover_students()`:

1. **Homepage extraction** (`homepage_discovery.py`) — Primary source for explicit relationships
   - `discover_homepage_urls()`: S2 homepage field → LLM URL suggestion → dedup
   - `fetch_homepage()`: Cached HTML fetching with `_HomepageTextExtractor` (HTMLParser subclass)
   - `extract_students_from_homepage()`: LLM extracts student names, status, research directions
   - Students get `source="homepage"`, `status` in ("current", "graduated", "postdoc", "unknown")

2. **Co-authorship analysis** (`student_discovery.py`) — Secondary, inferred relationships
   - `score_student_candidates()` scores co-authors on: first-author signal (40%), time concentration matching PhD period (25%), collaboration frequency (20%), recency (15%). Threshold: score ≥ 0.4
   - Students get `source="coauthorship"`

3. **Merge** — `_merge_student_lists()`: overlapping students get `source="both"`, homepage data takes priority
4. **LLM enrichment** — adds `research_direction` for coauthorship-only students

## Configurable Parameters

### Research Scout

Config at `~/.config/research_scout/config.json`. Resolution: CLI flag > `project.json` > `config.json` > hardcoded default (via `_resolve_param()`).

| Parameter | Config key | Default |
|-----------|-----------|---------|
| LLM backend | `default_api` | `ollama` (local Qwen3.6-35B; also `claude_cli`/`anthropic`/`openai`) |
| Hugo site path | `hugo_site` | `tools/website` |
| Lookback days | `default_lookback_days` | 7 |
| Max search results | `default_max_results` | 50 |
| Top papers in report | `default_top_papers_in_report` | 5 |
| Max high relevance | `max_high_relevance` | 20 |
| Output language | `--language` (CLI only) | `zh` |
| Insight top N | `default_insight_top_n` | 3 |
| Max fulltext chars | (hardcoded) | 40000 |

Per-project source configuration (in `project.json`): `sources`, `pubmed_journals`, `biorxiv_categories`, `lookback_days`, `max_results`.

### Researcher Profiler

Config at `~/.config/research/config.json` (separate from Scout config). Resolution: CLI > config > default. Note: `cmd_profile()` in `research_scout.py` also reads Scout's `config.json` as fallback for `default_api`.

| Parameter | Config key | Default |
|-----------|-----------|---------|
| Claude model | `model` | `sonnet` |
| Analysis mode | `default_mode` | `fast` |
| Recursive depth | `default_depth` | `1` |
| Max students/layer | `max_students` | `10` |
| Output directory | `output_dir` | `""` (empty = use default `outputs/` tree) |
| S2 API key | `semantic_scholar_api_key` | (none) |

## Key Implementation Details

### Research Scout
- **Language convention**: overview.md and report headers in Chinese; paper evaluation fields in English
- **Paper ID system**: Unified `paper_id` across sources; `_paper_id()` and `_paper_url()` helpers
- **Dedup early stop**: 5 consecutive known papers → stop fetching
- **Conference search**: `--conference` → arXiv `all:"CVPR 2025"` + comment post-filter; mutually exclusive with `--author`
- **bioRxiv/PubMed**: stdlib only (`urllib.request`, `xml.etree.ElementTree`), no new deps
- **JSON repair**: `repair_json_with_llm()` imported from `common.json_utils`
- **`--no-cache` scope**: bypasses every cache layer — search, Stage 1/2 eval, insight, **and Stage 3 citations** (citation cache is disabled, not just the eval caches)

### Researcher Profiler
- **LLM**: Multi-backend (`ollama` default/`claude_cli`/`anthropic`/`openai`) via `backend` parameter, 5min timeout
- **JSON parse**: non-LLM stages (direct parse → code block extract → brace matching → unescaped-quote fix) via `common.json_utils.try_parse_json`, then escalating LLM repair via `common.json_utils.repair_json_with_llm` (haiku → sonnet → opus, `max_chars=20000`, `timeout=300`)
- **Paper selection**: `_select_papers_by_year()` merges S2 (primary) + ArXiv (enriches arxiv_id, pdf_url, categories). Max 10 papers/year, sorted by award weight then citations. `_resort_after_awards()` re-sorts after LLM award identification
- **Fast vs detailed mode**: fast skips full-text download, uses `TRAJECTORY_ANALYSIS_PROMPT`; detailed downloads full texts (HTML first, PDF fallback via PyMuPDF) and uses `TRAJECTORY_ANALYSIS_DETAILED_PROMPT`
- **Rate limiting**: Thread-safe token-bucket; ArXiv 1 req/3s, S2 10 req/s, Web 1 req/2s (homepage fetching). S2 retries on 429 with escalating backoff (5, 10, 20, 40, 60s)
- **Top venues**: hardcoded set in `semantic_scholar.py` (ICRA, IROS, RSS, CoRL, NeurIPS, ICML, ICLR, CVPR, etc.)
- **Cache**: Namespaced (`api/arxiv/`, `api/semantic_scholar/`, `api/pdfs/`, `api/homepage/`, `llm/`), 7-day TTL for API results, no TTL for PDFs/LLM
- **Output**: Atomic writes via `.tmp` → `.replace()` throughout

## File Layout

```
research_scout.py                           # Research Scout backward-compat shim (~95 lines) → scout/ package
scout/                                      # Research Scout implementation (config, project, search, evaluate, insight, report, prompts, ask, cli)
TUTORIAL.md                                 # User docs for Research Scout (中文)

# Researcher Profiler (modular package)
__init__.py, __main__.py, cli.py
analysis.py, models.py, scoring.py, student_discovery.py, homepage_discovery.py
llm.py, prompts.py, cache.py, config.py, output.py
apis/{__init__.py, arxiv_client.py, semantic_scholar.py, rate_limiter.py, openreview_client.py}

# Shared
projects/<name>/{project.json, overview.md} # Project definitions (Research Scout)
```

### Output Paths (all under `outputs/` at repo root, gitignored)

Research Scout uses `common.paths` constants directly:
- `outputs/reports/research-scout/` — generated reports
- `outputs/cache/research-scout/eval/` — evaluation cache
- `outputs/cache/research-scout/papers/` — search result cache
- `outputs/cache/research-scout/insight/` — insight analysis cache (keyed by paper_id + content hash)
- `outputs/logs/research-scout/` — research_scout.log (rotating 5MB x 3)

Researcher Profiler resolves paths via `config.resolve_profiler_paths()` — custom `output_dir` overrides all:
- `outputs/data/research-profiler/profiles/` — JSON researcher profiles
- `outputs/reports/research-profiler/` — Markdown reports
- `outputs/cache/research-profiler/` — API + LLM response cache (namespaced: `api/arxiv/`, `api/semantic_scholar/`, `api/homepage/`, `api/pdfs/`, `llm/`)

## Dependencies

Research Scout: `arxiv>=2.0.0`, `anthropic>=0.18.0`, `openai>=1.0.0`, `openreview-py>=1.40.0` (in `requirements.txt`). bioRxiv/PubMed use stdlib. Shared utilities from `common/` (pip-installed). Optional: `PyMuPDF` (for PDF full-text extraction in `--insight` mode).

Researcher Profiler: `arxiv>=2.0.0` (in `requirements.txt`). Optional: `PyMuPDF` (PDF text extraction in detailed mode). LLM supports 4 backends (ollama/claude_cli/anthropic/openai) via `--api` flag. All API clients use stdlib `urllib.request`.
