# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

AI conversation summarization pipeline — two-phase architecture for daily reports plus weekly and monthly aggregation. Refactored from a monolith into a proper Python package (`summarize/`).

## Commands

```bash
conda activate AI
pip install -e ../..                 # install common/ package (required)
pip install -r requirements.txt      # anthropic and/or openai

# Unified CLI (preferred)
python -m summarize daily export --date 2026-02-13
python -m summarize daily export --date 2026-02-13 --summarize --api anthropic
python -m summarize daily export                                   # all unexported dates
python -m summarize daily merge --sync --date 2026-02-13 --deploy
python -m summarize daily merge --sync-all                         # batch all dates
python -m summarize daily merge --date 2026-02-13 --no-cache       # force re-call LLM
python -m summarize daily deploy --force
python -m summarize daily config --init
python -m summarize weekly generate --week 2026-W12 --deploy
python -m summarize weekly deploy                                  # replay saved weekly reports to Hugo (no LLM)
python -m summarize weekly list
python -m summarize monthly generate --month 2026-02 --deploy
python -m summarize monthly deploy --month 2025-10 --force         # replay one month (backs up before overwrite)
python -m summarize auto --deploy                                  # full pipeline: daily → weekly → monthly
python -m summarize auto --date 2026-04-18 --deploy                # target specific date
python -m summarize auto --force                                   # force regeneration

# Legacy entry points (still work via re-export shim)
python daily_summary.py export --date 2026-02-13
python weekly_summary.py generate --week 2026-W12
python monthly_summary.py generate --month 2026-02

# Tests
pytest tests/                        # all summarize tests
pytest tests/test_imports.py         # verify import contracts after refactoring
```

`--api` flag: `ollama` (default — local Ollama, keyless, Qwen3.6-35B), `claude_cli` (calls `claude --print`), `anthropic` (needs `ANTHROPIC_API_KEY`), `openai` (needs `OPENAI_API_KEY`). Override the default globally with `GADGET_LLM_BACKEND`, or per-user via config `default_api`.

## Architecture

### Package structure

The codebase was refactored from a single `daily_summary.py` monolith into focused sub-modules:

```
__main__.py        # Unified CLI: python -m summarize {daily,weekly,monthly,auto}
cli.py             # argparse for daily subcommands (export/merge/deploy/config)
config.py          # Config loading: _load_config(), _resolve_output_dir(), _get_device_name()
remote.py          # rclone upload/download utilities
parsers.py         # Conversation parsers: Claude Code, Codex, ChatGPT, generic JSON
usage.py           # Token usage tracking: ccusage 20.x per-source (discover/fetch/normalize/save/merge)
summarizer.py      # Prompt templates, conversation formatting, LLM dispatch
formatter.py       # Markdown rendering, Hugo post creation, bilingual output
daily.py           # Pipeline orchestration: cmd_export, cmd_merge, cmd_deploy, cmd_config
charts.py          # Token usage charts (3-subplot PNG: Tokens/Cost/Cache via matplotlib)
auto.py            # Full pipeline runner: daily export → merge → weekly → monthly (subprocess-based)
daily_summary.py   # Backward-compat re-export shim (all symbols from sub-modules)
llm_backends.py    # Re-export shim → delegates to common/ package
monthly_summary.py # Monthly pipeline (standalone, imports from common/ + config)
weekly_summary.py  # Weekly pipeline (standalone, imports from monthly + common/ + config)
```

`daily_summary.py` is a **re-export shim** — it re-exports every public symbol from the sub-modules so that `from daily_summary import ...` continues to work (used by monthly, weekly, and external consumers). New code should import from the specific sub-module.

### Dependency flow

```
cli.py → daily.py → {config, remote, parsers, usage, summarizer, formatter, charts}
                         ↓           ↓            ↓              ↓           ↓
                     common.io   common.llm   common.paths   common.bilingual  matplotlib (optional)
                                 common.json_utils           common.site_staging

weekly_summary.py  → monthly_summary.py + config + common/* + charts
monthly_summary.py → config + common/* + charts
auto.py            → subprocess calls to python -m summarize (no direct imports)
```

### Two-phase daily pipeline

**Phase 1 — Export** (`cmd_export` / `cmd_export_past`): Runs on each device locally. Scans `~/.claude/projects/` JSONL + `~/.codex/sessions/` + optional ChatGPT/generic sources. Outputs `logs/YYYY-MM-DD_<device>.json`. Also fetches token usage via ccusage 20.x — `discover_sources()` finds which agent CLIs have data (from the unified report's `metadata.agents`), then fetches each via `ccusage <source> daily --json --breakdown`, normalizes, and writes one `usage_<source>_<device>.json` per source. Optionally calls LLM for per-device summary (`--summarize`). Uploads to rclone remote.

**Phase 2 — Merge** (`cmd_merge`): Runs on central machine. Loads all device logs for a date, deduplicates, builds multi-device prompt, calls `_call_summarize()` → final report JSON + Markdown.

**Deploy** (`cmd_deploy`): Writes finalized reports as bilingual Hugo content directly into `tools/website/content/bugJournal/` via `common.site_staging`/`common.bilingual`, then triggers `run_hugo_update()`. Deployed-state = same-named file present in the content dir. `--force` redeploys, backing the previous generated file up to `outputs/backups/website-force/` first; files without a gadget marker are human-written and are never overwritten without `--overwrite-human`. Weekly/monthly have the same `deploy` subcommand (replay from saved `outputs/reports/summarize/*-weekly.md` / `*-monthly.md`, no LLM re-run — use this instead of `generate --force` when the report itself is fine).

**Auto** (`cmd_auto`): Subprocess-based orchestration — runs export → merge → weekly → monthly for a target date. Each step is a separate subprocess; failures don't block subsequent steps. When the pipeline completes it unloads all resident Ollama models (`_unload_ollama` → `common.engine._free_ollama_vram`; models stay warm between stages during the run — set `GADGET_KEEP_OLLAMA=1` to also keep them after).

### Token usage charts (`charts.py`)

Generates PNG charts via matplotlib (optional dependency — gracefully skipped if not installed):

- **Daily/Weekly charts** (`<date>-usage.png`): 3-subplot PNG — Tokens (platform × model stacked bar), Cost (platform × model stacked bar), Cache (platform × token type stacked bar)
- **Monthly charts**: `<month>-monthly-cost.png` (daily cost trend), `<month>-monthly-tokens.png` (daily token trend)
- Output directory: `outputs/images/summarize/`

### LLM call flow for large inputs

When content exceeds 150K chars, `_call_summarize()` (in `summarizer.py`) uses hierarchical merge:

1. `chunk_conversations()` splits by conversation boundaries
2. Each chunk → `timed_llm_call()` with per-chunk timeout + auto JSON repair
3. Chunk results cached in `outputs/cache/summarize/chunks/<date>/` (keyed by content hash + global hash)
4. `hierarchical_merge()` recursively merges chunk summaries (3x timeout for merge phase)

Monthly uses week-based grouping; weekly uses front-half/back-half grouping.

## Key data formats

**Export log** (`logs/YYYY-MM-DD_<device>.json`): `{version, date, device, conversations[], device_summary{}, token_usage, _merged_devices[], _finalized}`

**Report** (`reports/YYYY-MM-DD.json`): `{date, summary, daily_overview, tasks[], problems_and_solutions[], human_vs_ai[], ai_limitations[], learnings[], conversation_summaries[], token_usage_by_source{<source>: usage}, token_usage, codex_token_usage}` — `token_usage_by_source` is canonical (one entry per discovered source); `token_usage` (Claude Code) and `codex_token_usage` are retained as backward-compat aliases.

**Weekly Report** (`reports/YYYY-WNN-weekly.json`): `{week, date_range{start,end}, summary, project_progress[], key_tasks[], problems_resolved[], learnings[], ai_usage_notes{}, next_week_outlook, statistics, token_usage_summary, codex_token_usage_summary, combined_token_usage_summary}` — ISO 8601 weeks (Monday–Sunday).

Every item in tasks/problems/learnings has `level: "high"|"low"` and `importance: 1-10` for priority sorting.

## Config resolution

CLI flag > env var (`SUMMARIZE_LOGS_DIR` / `SUMMARIZE_REPORTS_DIR`) > config file > hardcoded default (`outputs/logs/summarize/`, `outputs/reports/summarize/`).

Config file location: `SUMMARIZE_CONFIG` env var (explicit path — beats both lookups; used for test isolation) > repo-local **`tools/summarize/config.json`** (gitignored — copy `config.example.json`; `config --init` writes here) > legacy per-user `~/.config/summarize/config.json` when the repo-local one is absent.

**Config-driven CLI defaults** — so `python -m summarize auto` (and daily/weekly/monthly) run "the way I want" with no flag soup. `config.py::cli_defaults()` maps config keys to argparse dests; each parser calls `set_defaults(**cli_defaults())` before `parse_args` (per-subparser for daily/weekly/monthly, since a subparser default overrides a parent's). A CLI flag still wins over config. `config.py::apply_env_from_config()` (called at the top of `__main__.main()`) bridges the local-LLM/translation knobs into env via `os.environ.setdefault` so `common.llm` (ollama path) / `common.engine` (translation) pick them up unchanged — a real exported env var still wins. This replaces the `eval "$(bash scripts/serve_local_llm.sh env)"` step for a persistent local setup.

Config keys:
- Paths/identity: `device_name`, `logs_dir`, `reports_dir`, `rclone_remote`, `rclone_path`
- CLI-default behavior (via `cli_defaults`): `default_api` (→ `--api`), `deploy`, `hugo_site`, `workers`
- Local-LLM / translation (via `apply_env_from_config`, → env): `model` (`OLLAMA_MODEL`), `base_url` (`OLLAMA_BASE_URL`), `reasoning_effort` (`OPENAI_REASONING_EFFORT`), `translation_model` (`GADGET_TRANSLATION_MODEL`), `translation_model_ollama` (`OLLAMA_TRANSLATION_MODEL`), `translation_backend` (`GADGET_TRANSLATION_BACKEND`)

## Cross-module import contract

`daily_summary.py` (the re-export shim) is the stable API surface — used by the monthly/weekly pipelines. The `tests/test_imports.py` file parametrically verifies all expected symbols survive refactoring. Run it after any structural changes.

Key exports consumed externally:
- **By weekly/monthly**: `_atomic_write`, `_resolve_output_dir`, `_load_config`, `run_hugo_update`, `format_reports_for_llm`, `aggregate_token_usage`

## Output directories

All outputs go to the unified `outputs/` tree at the project root:

- `outputs/logs/summarize/` — export logs, ccusage/codex_usage snapshots
- `outputs/reports/summarize/` — final daily/weekly/monthly JSON + Markdown
- `outputs/images/summarize/` — token usage charts (daily/weekly/monthly PNGs)
- `outputs/cache/summarize/` — chunk cache (daily), `weekly/`, `monthly/`
