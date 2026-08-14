# tools/summarize — AI Conversation Reports

Generates daily/weekly/monthly summaries of AI conversation logs (Claude Code / Codex / Cursor Agent / ChatGPT / generic JSON) via LLM, with token-usage stats from ccusage. Two-phase daily pipeline (per-device `export` → aggregate `merge`), weekly/monthly aggregation, and one-click `auto` orchestration (`auto.py` drives the subcommands via subprocess). Unified CLI is `python -m summarize`; legacy `daily_summary.py` / `weekly_summary.py` / `monthly_summary.py` entry points still work as re-export shims.

## Commands

```bash
python -m summarize onboard                            # check/setup requirements for auto mode
python -m summarize daily export                       # phase 1: export all unexported dates
python -m summarize daily merge --sync-all             # phase 2: sync all dates + merge day by day
python -m summarize weekly generate --week 2026-W12 --deploy
python -m summarize monthly generate --month 2026-02 --deploy
python -m summarize auto --deploy                      # full pipeline: export → merge → weekly → monthly + deploy
python -m summarize daily config --init                # first-time config
cd tools && python -m pytest summarize/tests           # unit tests (pure mock, no network/keys)
```

LLM backend via `--api`: `ollama` (default) / `claude_cli` / `anthropic` / `openai`. Optional: Node.js for ccusage token stats, matplotlib for `charts.py` PNG charts.

## Quirks

- `tests/test_daily_e2e.py` needs a live Ollama + translation model + local device logs — it auto-skips otherwise. Run with `eval "$(bash scripts/serve_local_llm.sh env)"` first.
- `auto` unloads resident Ollama models when the pipeline completes; set `GADGET_KEEP_OLLAMA=1` to keep them warm (e.g. back-to-back cron runs).
- Keep JSON field names stable (`token_usage`, `conversation_summaries`, `device_name`, `_finalized`) — merge and renderers parse them across devices.
- Exported logs and reports go to `outputs/{logs,reports,cache}/` and may contain sensitive conversation content — never commit them.
