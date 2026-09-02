# Debugging Guide

Where logs and caches live, how config resolves, the hidden side effects that
bite, and how to isolate a failure to one stage. Cited to `file:line`.

## Config resolution order

Uniform: **CLI flag > env var > config.json > hardcoded default**, implemented
per tool. One file for every tool: **`GADGET_CONFIG`** (explicit path — tests /
multi-config) else repo-root **`<GADGET_ROOT>/config.json`**. There is no
`SUMMARIZE_CONFIG`, and **`~/.config/summarize` / `~/.config/research` are not
read**. Missing file or section → `{}`. Template: `config.example.json`.
Sections: `summarize`, `research`, `research_scout`, `sync`, `translator`.
Resolver: `common.config.resolve_config_path()` (`common/config.py:39-44`).

- **summarize paths** — `_resolve_output_dir(cli, env_key, config_key, default)` (`tools/summarize/config.py:39-59`): CLI arg > env (`SUMMARIZE_LOGS_DIR` / `SUMMARIZE_REPORTS_DIR`) > `summarize` section (`logs_dir`/`reports_dir`) > default under `outputs/`. Relative paths are rooted at the gadget repo.
- **summarize behavior defaults** (`api`/`deploy`/`hugo_site`/`workers`) — `cli_defaults()` maps config keys to argparse dests via `parser.set_defaults` (`config.py:84-108`); an explicit flag still overrides.
- **summarize LLM/translation knobs** — `apply_env_from_config()` bridges config → env via `os.environ.setdefault` (`config.py:122-130`): `model→OLLAMA_MODEL`, `base_url→OLLAMA_BASE_URL`, `reasoning_effort→OPENAI_REASONING_EFFORT`, `translation_model→GADGET_TRANSLATION_MODEL`, `translation_model_ollama→OLLAMA_TRANSLATION_MODEL`, `translation_backend→GADGET_TRANSLATION_BACKEND`. Because it's `setdefault`, a real exported env var wins over config.
- **research** — `resolve_param(args, project, name, default)` (`scout/config.py:86-94`): CLI > `project.json[name]` > merged config `default_<name>` > default. `load_scout_config()` (`scout/config.py:56-69`) merges the same root file's `research_scout` + `research` sections; scout keys win.
- **LLM backend** — `DEFAULT_BACKEND` is `os.environ.get("GADGET_LLM_BACKEND") or "ollama"` (`llm.py:53`; empty env still falls back to `ollama`). Per-call `backend` / `--api` overrides. An unknown backend raises `ValueError` (valid: `LLM_BACKENDS` at `llm.py:58`) instead of silently running `claude_cli`.
- **Translation backend** — `GADGET_TRANSLATION_BACKEND` explicit > auto-detect ollama→vllm→llamacpp→transformers (`engine.py:800-860`; an unknown non-empty value raises `ValueError` instead of silently auto-selecting); model = arg > `GADGET_TRANSLATION_MODEL` > default (`engine.py:89-94`). The in-process engine cache is keyed by `(backend, model_id)`, so switching backend mid-process yields a fresh engine, not a stale one.

## Where logs live

| Tool | Path | Notes |
|---|---|---|
| summarize export | `outputs/logs/summarize/<date>_<device>.json` | export logs + usage snapshots (`daily.py:102`) |
| summarize merge | `outputs/logs/summarize/merge_logs/merge_<date>.log` | per-date merge subprocess stdout+stderr, opened `w` (`daily.py:307`) |
| summarize deploy | **`outputs/reports/logs/deploy.log`** | ⚠️ under `outputs/reports`, not `outputs/logs`; opened `w` — **truncated every deploy** (`daily.py:880-881`) |
| research | `outputs/logs/research-scout/research_scout.log` | rotating 5 MB × 3; DEBUG→file, INFO→stdout; created even for read-only commands (`scout/config.py:136-147`) |
| research profiler | *(no dedicated file — reuses the `research_scout` logger)* | |

## Where caches live

Base: `outputs/cache/` (`paths.py:10`). `DiskCache` stores
`<cache_dir>/<namespace>/<sha256(key)>.json` with TTL (`cache.py:23-45`).

| Cache | Path | Notes |
|---|---|---|
| summarize final report | `outputs/cache/summarize/<date>.json` | skipped by `--no-cache`/`--force` (`daily.py:646-650`) |
| summarize chunks | `outputs/cache/summarize/chunks/<date>/<hash>.json` | **auto-deleted** after final report cached (`daily.py:677` → `llm.py:474`); a crash leaves them behind |
| research scout eval | `outputs/cache/research-scout/eval/{screening,deep}_<hash>.json` | quality-gated — LLM-failure results are **not** cached (`evaluate.py:451-454,492-495`) |
| research scout search | `outputs/cache/research-scout/papers/*.json` | hard failure (`None`) not cached (`search.py:856-863`) |
| research scout insight | `outputs/cache/research-scout/insight/<hash>.json` | Stage 4/5 only (`insight.py:141-153`) |
| research API (S2/arxiv/openreview/pdfs) | `outputs/cache/research-scout/` namespaces `api/*` | Stage-3 citations + full-text; disabled by `--no-cache` |
| research profiler | `outputs/cache/research-profiler/` namespaces `api/*`, `llm` | (`config.py:121`) |

## Hidden side effects (know these before you debug)

1. **`create_engine()` evicts the resident Ollama chat model.** When the chosen translation engine is **not** `OllamaEngine`, `common/engine.py:864-865` calls `_free_ollama_vram()`, which POSTs `keep_alive:0` for every resident model — unloading e.g. `gemma4:26b`. The next summarize chat call then cold-reloads (~8 s). Fires on any deploy/translate step using llamacpp/transformers/vllm. To avoid: `GADGET_TRANSLATION_BACKEND=ollama`, or `GADGET_KEEP_OLLAMA=1` to keep the chat model resident regardless of backend.
2. **`apply_env_from_config()` mutates `os.environ` at startup** (`config.py:122-130`) for the whole run — affects `common.llm`/`common.engine` even in subcommands you didn't expect.
3. **`deploy.log` is truncated every run** (opened `w`, `daily.py:881`) and lives under `outputs/reports/logs/` — easy to miss.
4. **`_finalized` flags**: export marks past-date logs finalized (`daily.py:193-200`), merge marks past-date reports finalized (`:711`). Once set, re-running export/merge **silently skips** that date unless `--force`.
5. **rclone side effects on export/merge**: `merge --sync-all` **downloads** remote logs/reports into local dirs before processing (`daily.py:323,331`), possibly overwriting.
6. **`search_all_projects` writes `project.json`**: sets `last_searched=today` and saves as a side effect of searching (`search.py:499-500`).

## Isolate a failure by stage

**summarize** (parse → summarize → render → deploy):

- **parse** — `python -m summarize daily export --date D` **without** `--summarize` (no LLM); inspect `outputs/logs/summarize/D_<device>.json` `conversations[]`. Empty ⇒ `parsers.collect_conversations` failed, not the LLM.
- **summarize/LLM** — `daily merge --date D --no-cache` forces a fresh call bypassing `outputs/cache/summarize/D.json`; watch chunk cache `outputs/cache/summarize/chunks/D/` and (for `--sync-all`) `merge_logs/merge_D.log`. `ChunkTimeoutError` surfaces here.
- **render** — run merge **without** `--deploy`; read `outputs/reports/summarize/D.{json,md}`. Bad report there isolates `generate_markdown`/`save_report` from deploy. Chart issues are separate: `outputs/images/summarize/D-usage.png`.
- **deploy/translate** — `daily deploy --date D`; read `outputs/reports/logs/deploy.log`. Translation/bilingual failures appear here. Set `GADGET_TRANSLATION_BACKEND=ollama` to avoid the VRAM-eviction slowdown.

**research** (search → screen → eval → report):

- **search** — `search --project P --no-cache`; inspect `outputs/cache/research-scout/papers/*.json` and `找到 N 篇` lines in the log. `None` vs `[]` distinguishes hard failure from empty.
- **screen (Stage 1)** — check `eval/screening_<hash>.json` and `have empty motivation/innovation_point` warnings (`evaluate.py:234-239`); all-empty ⇒ LLM failed (deliberately not cached).
- **eval (Stage 2/3)** — `eval/deep_<hash>.json` + `composite_score=0` warnings; Stage-3 citations hit the `api/semantic_scholar` namespace (`无法在 S2 找到论文`).
- **report/insight** — reports in `outputs/reports/research-scout/`; `--insight` adds Stage 4/5 with `insight/` cache. `--no-cache` busts all layers; swap `--api`/`GADGET_LLM_BACKEND` to separate parse errors from model errors.
- **general** — the file log is DEBUG-level (`config.py:143`), so `research_scout.log` has per-stage timing that stdout (INFO) omits — tail it to see which stage stalled.

## Quick smoke check

`bash scripts/smoke.sh` — read-only `--help`/`--info`/config-show/import checks
across every tool. Confirms "does it start and parse" (not correctness). See
`development.md` for test commands.
