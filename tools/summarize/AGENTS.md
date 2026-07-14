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
python tools/summarize/daily_summary.py config --show            # Config resolution
python tools/summarize/daily_summary.py export --date 2026-02-13 # Export validation
python tools/summarize/monthly_summary.py list                   # Report discovery
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

- Never commit conversation logs, API keys, or the summarize config (repo-local `tools/summarize/config.json` — gitignored — or `~/.config/summarize/config.json`)
- Treat device names and exported JSON as potentially sensitive
