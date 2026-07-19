# AGENTS.md — summarize module

> **Workflow Protocol**: Follow [../../AGENTS.md](../../AGENTS.md) — AI Dev Companion pipeline (/ccdiscuss → /ccplan → /ccedit → /ccdebug; plans in `../../docs/ecl/*.yaml`).
> Paraphrase the task and get explicit confirmation before editing code.

## Module Scope

- `daily_summary.py` — main daily pipeline (export, merge, deploy, config)
- `monthly_summary.py` — monthly reports from daily JSON
- `weekly_summary.py` — weekly aggregation
- `auto.py` — full-pipeline orchestration (daily → weekly → monthly)
- `formatter.py` — bilingual markdown formatting
- `charts.py` — token usage PNG charts
- `llm_backends.py` — compatibility shim for `../../common/`

## Verification Commands

Use these to verify changes to this module:

```bash
python -m pytest tools/summarize/tests/                          # Unit tests
python -m summarize daily config --show                          # Config resolution
python -m summarize daily export --date 2026-02-13               # Export validation
python -m summarize monthly list                                 # Report discovery
```

## Coding Conventions

- PEP 8, 4-space indent, `snake_case` functions, `UPPER_CASE` constants
- Typed Python with `Path`, `dict`, `Optional[...]` annotations
- Stable JSON field names: `token_usage`, `conversation_summaries`, `device_name`, `_finalized`
- Generated files → `outputs/{logs,reports,cache}/summarize/`, never in source control

## File Conventions

| Purpose | Location |
|---------|----------|
| Plans / ECL | `../../docs/ecl/*.yaml` |
| Change tracking | `../../.devcompanion/` |

## Security

- Never commit conversation logs, API keys, or the repo-root `config.json` (gitignored; contains the `summarize` section)
- Treat device names and exported JSON as potentially sensitive
