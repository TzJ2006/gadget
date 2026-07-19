# AGENTS.md — research module

> **Workflow Protocol**: Follow [../../AGENTS.md](../../AGENTS.md) — AI Dev Companion pipeline (/ccdiscuss → /ccplan → /ccedit → /ccdebug; plans in `../../docs/ecl/*.yaml`).
> Paraphrase the task and get explicit confirmation before editing code.

## Module Scope

- `scout/` — paper discovery package (search, evaluate, report, insight, ask)
- `research_scout.py` — backward-compat CLI shim
- `apis/` — arXiv, OpenReview, Semantic Scholar clients with rate limiting
- Profiler: `models.py`, `scoring.py`, `analysis.py`, `student_discovery.py`, `homepage_discovery.py`
- `cache.py` — re-export shim for `common.cache.DiskCache`
- `llm.py` — imports `common.llm.call_llm_raw` + `common.json_utils`

## Verification Commands

Use these to verify changes to this module:

```bash
python -m research --help                                         # CLI loads without error
python tools/research/research_scout.py search --query "test" --limit 1 # Search smoke test
python -c "from research.cache import DiskCache; print('OK')"     # Import chain check
```

## Coding Conventions

- PEP 8, typed Python, `Path`-based file handling
- All LLM calls via `common.llm` — no direct API usage in this module
- Cache via `common.cache.DiskCache` with namespace separation
- Generated outputs → `outputs/{reports,cache}/research/`

## File Conventions

| Purpose | Location |
|---------|----------|
| Plans / ECL | `../../docs/ecl/*.yaml` |
| Change tracking | `../../.devcompanion/` |

## Security

- Never commit API keys or the repo-root `config.json` (gitignored; contains `research` / `research_scout` sections)
- arXiv/Semantic Scholar API keys go in environment variables only
