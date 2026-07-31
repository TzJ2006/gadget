# tools/research — Paper Discovery & Researcher Analysis

Unified research toolkit: paper discovery over arXiv/bioRxiv/PubMed with a three-stage LLM pipeline, deep paper insight (`--insight`: full text + OpenReview reviews), researcher profiling (ArXiv + Semantic Scholar), and citation-graph analysis. `research_scout.py` is a backward-compat shim over the `scout/` package (search / evaluate / report / insight / ask); the profiler is `models.py` / `scoring.py` / `analysis.py` / `student_discovery.py` / `homepage_discovery.py`; rate-limited API clients live in `apis/`.

## Commands (from repo root)

```bash
python tools/research/research_scout.py report --project my-project   # full pipeline: search → eval → report
python tools/research/research_scout.py ask "natural-language query"  # auto-routes source
python tools/research/research_scout.py search --conference "CVPR 2025"
python tools/research/research_scout.py profile "Sergey Levine"
python tools/research/research_scout.py citations 2301.12597          # arXiv ID or DOI
python tools/research/research_scout.py deploy                        # publish reports to Hugo
python -m research --help                                             # standalone profiler entry (analyze/show/list/config)
cd tools && python -m pytest research/tests                           # unit tests (LLM mocked)
```

Subcommands: `init / ask / list / search / report / profile / citations / deploy / config`. LLM backend via `--api`: `ollama` (default) / `claude_cli` / `anthropic` / `openai`.

## Quirks

- All LLM calls go through `common.llm` — never call provider SDKs directly in this module.
- `cache.py` is a re-export shim for `common.cache.DiskCache` — keep the import path alive.
- Optional deps: `openreview-py` (reviewer analysis in `--insight`), PyMuPDF (PDF full-text extraction); bioRxiv/PubMed clients are stdlib-only.
- Config lives in the repo-root `config.json` sections `research` / `research_scout` (gitignored); project state under `projects/`; outputs/caches under `outputs/`.
