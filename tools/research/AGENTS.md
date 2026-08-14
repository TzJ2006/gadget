# tools/research — Paper Discovery & Researcher Analysis

Unified research toolkit: paper discovery over arXiv/bioRxiv/PubMed with a three-stage LLM pipeline, deep paper insight (`--insight`: full text + OpenReview reviews), researcher profiling (ArXiv + Semantic Scholar), and citation-graph analysis.

**Layout.** Scout logic lives in `tools/research/scout/` (installed package `research.scout`: `search` / `evaluate` / `report` / `insight` / `ask` / `cli`). `research_scout.py` is a deprecation shim over that package. The profiler is `models.py` / `scoring.py` / `analysis.py` / `student_discovery.py` / `homepage_discovery.py`; rate-limited API clients live in `apis/`. Project defs live in `tools/research/projects/` (gitignored except `.gitkeep`).

**Install.** From repo root: `pip install -e ".[research]"` — that extra is the source of truth (`tools/research/requirements.txt` only points here).

## Commands (from repo root)

```bash
python -m research.scout report --project my-project   # full pipeline: search → eval → report
python -m research.scout ask "natural-language query"  # auto-routes source
python -m research.scout search --conference "CVPR 2025"
python -m research.scout profile "Sergey Levine"
python -m research.scout citations 2301.12597          # arXiv ID or DOI
python -m research.scout deploy                        # publish reports to Hugo
python -m research --help                              # standalone profiler entry (analyze/show/list/config)
cd tools && python -m pytest research/tests            # unit tests (LLM mocked)
```

Subcommands: `init / ask / list / search / report / profile / citations / deploy / config`. LLM backend via `--api`: `ollama` (default) / `claude_cli` / `anthropic` / `openai`.

## Quirks

- All LLM calls go through `common.llm` — never call provider SDKs directly in this module.
- `cache.py` is a re-export shim for `common.cache.DiskCache` — keep the import path alive.
- Config lives in the repo-root `config.json` sections `research` (profiler) and `research_scout` (scout; merged — scout keys win). Override path with `GADGET_CONFIG`. **Not** `~/.config/research` or `~/.config/research_scout`.
- Outputs/caches under `outputs/`. Homepage fetches go through SSRF checks in `homepage_discovery.py`.
