# CLAUDE.md

@AGENTS.md

## Claude Code notes

- Never run these in a foreground Bash call — they block forever: `hugo server -D` (watch mode), `python -m translator` (Gradio GUI), `bash scripts/serve_local_llm.sh` serve mode (`eval "$(bash scripts/serve_local_llm.sh env)"` is fine — it only prints env).
- A full `python -m benchmark.cli` run takes minutes and loads torch; for smoke checks use `--info` (no CSV write) or `--cpu-only --duration 3`.
- `python -m summarize auto --deploy`, `research_scout.py report`, and `update.sh` make LLM calls and/or push to the live site — don't run them just to verify code; use `bash scripts/smoke.sh` and the per-tool pytest suites instead.
- Each tool dir has its own `AGENTS.md`/`CLAUDE.md` with verification commands — check those first when working inside `tools/<tool>/`.
