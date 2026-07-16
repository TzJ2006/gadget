# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python 3.10+ utility toolkit of standalone scripts — no build system; per-module `pytest` suites (see **Tests**). Each top-level directory is an independent tool. All paths are dynamically resolved relative to the project root; `website/` contains site-specific deployment URLs (GitHub Pages) that may need updating for a different deployment target.

**Sub-project CLAUDE.md files** exist with detailed module-specific docs — check these first when working within a tool:
- `tools/summarize/CLAUDE.md` — daily/weekly/monthly pipeline, auto mode, data formats, import contract
- `tools/research/CLAUDE.md` — evaluation pipeline, profiler architecture, citation graph API, configurable parameters
- `tools/benchmark/CLAUDE.md` — benchmark modules, measurement methodology, platform/dtype support matrices
- `tools/website/CLAUDE.md` — Hugo build pipeline, content sections, conventions

**Deep-dive reference docs** in `docs/reference/` (facts cited to `file:line`):
- `architecture.md` — source-of-truth layering map. The one rule: hub-and-spoke — all shared code in `common/`, **no tool imports another tool** (cross-tool interaction only via subprocess or reading the other tool's config), and `common/` never imports from `tools/`.
- `development.md` — golden paths for extending gadget (add a translation backend / LLM chat backend / daily-report field / config key / new tool), each with the exact edit sites **and the silent failure** if you miss one.
- `debugging.md` — log/cache locations, per-tool config resolution, hidden side effects, stage isolation.
- `tools.md` — per-tool run commands and output locations.

User-facing walkthroughs: `TUTORIAL.md` (root) and `docs/guides/`; Chinese versions in `docs/README.zh.md` / `docs/TUTORIAL.zh.md`.

Each tool module lives under `tools/` (`tools/summarize/`, `tools/research/`, `tools/benchmark/`, `tools/website/`, `tools/translator/`) and also has its own `AGENTS.md` that points back to the root protocol — see **Agentic Workflow** below.

## Environment Setup

- **Python**: Requires Python 3.10+. Uses conda environment `AI` (`conda activate AI`).
- **Windows**: Use PowerShell or Git Bash. Forward-slash paths work in Python; backslash in native shell.
- **Dependencies**: Each tool has its own `requirements.txt` — install with `pip install -r <tool>/requirements.txt`.
- **Install**: `pip install -e .` (or `pip install -e ".[all]"` for all tool deps) installs the `common/` package and the tool packages. `build/` and `gadget.egg-info/` are pip editable-install artifacts — gitignored, do not commit.
- **Translation** (for bilingual content): four backends, auto-selected by `common.engine.create_engine()`:
  - Ollama (`OllamaEngine`, **default**) — no extra deps; shares VRAM with the local chat model when the tag is pulled (`ollama pull hf.co/tencent/Hy-MT2-1.8B-GGUF`)
  - `pip install -e ".[translation]"` → torch + transformers (`TransformersEngine`)
  - Linux: optionally `pip install vllm>=0.8` for `VLLMEngine` (faster batch inference)
  - `pip install -e ".[translation-gguf]"` → llama-cpp-python + huggingface-hub (`LlamaCppEngine`, low-memory GGUF, no PyTorch)

  Default model `tencent/Hy-MT2-1.8B` (GGUF variant `tencent/Hy-MT2-1.8B-GGUF`), auto-downloaded on first run.

## Quick Reference Commands

```bash
# Summarize — unified CLI (preferred): python -m summarize {daily,weekly,monthly,auto,onboard}
python -m summarize onboard                                       # Check/setup requirements for auto mode
python -m summarize daily export                                  # Export all unexported dates
python -m summarize daily export --date 2026-02-13 --summarize    # Export + per-device AI summary
python -m summarize daily merge --sync-all                        # Sync all dates + batch merge
python -m summarize daily deploy                                  # Deploy undeployed reports to Hugo
python -m summarize daily config --init                           # First-time config
python -m summarize weekly generate --week 2026-W12 --deploy      # Weekly report + deploy
python -m summarize weekly deploy                                 # Replay-deploy saved weekly reports (no LLM re-run)
python -m summarize weekly list                                   # List available weeks
python -m summarize monthly generate --month 2026-02 --deploy     # Monthly report + deploy
python -m summarize monthly deploy --month 2025-10                # Replay-deploy a saved monthly report (no LLM re-run)
python -m summarize auto --deploy                                 # One-click: daily → weekly → monthly + deploy
python -m summarize auto --date 2026-04-18                        # Target a specific date
# Legacy entry points still work via re-export shims:
#   python tools/summarize/daily_summary.py … | weekly_summary.py … | monthly_summary.py …

# Benchmarks — must cd into tools/benchmark/ first
cd tools/benchmark && python -m benchmark.cli                # Run all benchmarks
cd tools/benchmark && python -m benchmark.cli --cpu-only     # CPU only
cd tools/benchmark && python -m benchmark.cli --report       # Run + generate HTML report
cd tools/benchmark && python -m benchmark.cli --report --deploy  # Run + report + deploy to Hugo

# Research — paper scout
python tools/research/research_scout.py report --project my-project --api claude_cli  # Full pipeline (search→eval→report)
python tools/research/research_scout.py report --project my-project --insight          # + Stage 4/5: full-text insight + OpenReview
python tools/research/research_scout.py ask "找 Pieter Abbeel 最近的机器人操作论文"      # Natural-language search (auto-routes source)
python tools/research/research_scout.py search --conference "CVPR 2025"               # Conference search
python tools/research/research_scout.py deploy                                        # Deploy to Hugo

# Research — profiler
python tools/research/research_scout.py profile "Sergey Levine"                       # Analyze researcher
python tools/research/research_scout.py profile "Name" --depth 1                      # + discover students
python -m research analyze "Sergey Levine"                                      # Standalone entry

# Research — citation graph
python tools/research/research_scout.py citations 2301.12597                          # By arXiv ID

# Website
cd tools/website && bash update.sh      # Incremental compress + Hugo build + deploy
cd tools/website && hugo server -D      # Dev server

# Sync — rclone-based data sync with Google Drive
python scripts/sync.py push                      # Local → remote
python scripts/sync.py pull                      # Remote → local
python scripts/sync.py status                    # Show diff
python scripts/sync.py push --category summarize # Sync one category only
python scripts/sync.py config --init             # First-time rclone config

# Smoke test — fast safety net for any change (read-only: --help/--info/import checks, no LLM/network/writes)
bash scripts/smoke.sh
```

All LLM-using tools support `--api` flag: `ollama` (default — local Ollama, keyless, runs Qwen3.6-35B; override globally with `GADGET_LLM_BACKEND`), `claude_cli` (calls `claude --print`), `anthropic` (needs `ANTHROPIC_API_KEY`), `openai` (needs `OPENAI_API_KEY`). Translation likewise defaults to Ollama (HY-MT2-1.8B) when the model is pulled, else falls back to the in-process GGUF/transformers engine — switch with `GADGET_TRANSLATION_BACKEND` (`ollama`/`llamacpp`/`vllm`/`transformers`).

## MCP Server

There is **no MCP integration**. An earlier refactor removed the server module (`mcp_server.py`) and its `gadget-mcp` console script; the now-dead `.mcp.json` registration was deleted too. To add MCP support, create a server module with a `main()` entry point, register a `[project.scripts]` entry in `pyproject.toml`, and add a fresh `.mcp.json`.

## Architecture

- **common/** — Shared utility package (pip-installed via `pyproject.toml`):
  - `paths.py`: `GADGET_ROOT`, `OUTPUTS_DIR`, `REPORTS_DIR`, `LOGS_DIR`, `CACHE_DIR`, `DATA_DIR`, `IMAGES_DIR` — canonical output paths under `outputs/`
  - `io.py`: `atomic_write()`, `content_hash()`, `load_json_config()`
  - `cache.py`: `DiskCache` — SHA-256 keyed disk cache with namespaces and TTL
  - `json_utils.py`: `parse_json_response()` (4-stage: direct → code block → depth brace match → fix unescaped quotes), `try_parse_json()`, `repair_json_with_llm()`, `try_repair_result()`
  - `llm.py`: Two-tier API — `call_llm_raw()` returns raw text; `call_llm()`/`call_anthropic()`/`call_openai()`/`call_claude_cli()` return parsed JSON dict with SDK-specific features (tool_use, json_object format). Also: `LLMCallConfig` dataclass, chunking utilities (`chunk_text`, `timed_llm_call`, `hierarchical_merge`, chunk cache)
  - `engine.py`: `TranslationEngine` ABC + four backends — `OllamaEngine` (auto-preferred default, shares the local Ollama server), `TransformersEngine` (Windows), `VLLMEngine` (Linux), `LlamaCppEngine` (GGUF, low-memory, no PyTorch) — selected by the `create_engine()` factory. Default model: `tencent/Hy-MT2-1.8B` (GGUF: `DEFAULT_TRANSLATION_MODEL_GGUF` = `tencent/Hy-MT2-1.8B-GGUF`; Ollama tag `DEFAULT_TRANSLATION_MODEL_OLLAMA` = `hf.co/tencent/Hy-MT2-1.8B-GGUF`). Also: `resolve_translation_model()`, `DEFAULT_TRANSLATION_MODEL`, `SAMPLING_DEFAULTS`, `_CachedEngineProxy`
  - `translation.py`: `translate_markdown_document()` — high-level markdown translation via local inference (vLLM/transformers), preserving frontmatter/shortcodes. Also: `detect_language()` (CJK ratio heuristic), `zh_path()` (.md → .zh.md), `clean_translated_document()`, `build_translation_prompt()`
  - `bilingual.py`: `write_bilingual()` — detects source language, writes original + translated counterpart (.md/.zh.md pair) via local inference engine. Used by summarize, research, and website deploy pipelines.
  - `hugo.py`: `run_hugo_update()` — cross-platform Hugo deploy
  - `site_staging.py`: `write_site_content()`, `copy_site_static()` — write auto-generated Hugo content/static files **directly into the Hugo site tree** (`resolve_site_staging_root(hugo_site) == hugo_site`, default `tools/website`). There is no separate staging tree. Written content is stamped `gadget_generated: true`; an existing file without a gadget marker is human-written and raises `HumanContentError` unless `overwrite_human=True`
  - `website_backup.py`: generated/human ownership rule (`classify_file`, `classify_content`, `stamp_generated`) + force-overwrite backups — `force=True` backs the previous file up into `outputs/backups/website-force/YYYYMMDD-HHMMSS/` (with `manifest.json`: sha256, paths, ownership, action, reason) before overwriting; backups are never auto-deleted
- **tools/** — The five standalone tool products (grouped for navigability):
  - **tools/summarize/** — AI conversation summarization (see `tools/summarize/CLAUDE.md`): Two-phase daily pipeline (export → merge) + weekly/monthly aggregation + full-pipeline auto mode. Refactored into sub-modules with unified CLI (`python -m summarize`). `llm_backends.py` is a re-export shim for `common/`. New: `auto.py` (daily→weekly→monthly orchestration; frees all resident Ollama models when the pipeline completes — `GADGET_KEEP_OLLAMA=1` keeps them warm), `charts.py` (token usage PNG charts via matplotlib), `onboarding.py` (`python -m summarize onboard` — checks/sets up requirements for auto mode; config template `config.example.json`).
  - **tools/research/** — Unified research toolkit (see `tools/research/CLAUDE.md`): Paper discovery (modular `scout/` package), researcher profiler (modular package), citation graph analysis. `research_scout.py` is a backward-compat shim — actual logic in `scout/`. `cache.py` is a re-export shim for `common.cache.DiskCache`.
  - **tools/benchmark/** — CPU/GPU benchmark suite (see `tools/benchmark/CLAUDE.md`): Modular `benchmark/` package with CSV append mode for multi-hardware accumulation. Renamed from `test/`.
  - **tools/website/** — Hugo blog (see `tools/website/CLAUDE.md`): PaperMod theme, incremental image/video compression, GitHub Pages deploy.
  - **tools/translator/** — Gradio document translator: `core.py` (translation logic over the `common.engine` backends), `app.py` (Gradio UI wiring), `__main__.py` (`python -m translator`). Optional-dependency extra `translator` (gradio + translation-gguf).
- *(Skills moved out)* — all Claude Code skills (gadget domain skills + the generic AI-dev/methodology skills) now live in the separate **ai-companion** repo (`git@github.com:TzJ2006/ai-companion.git`), checked out at the sibling `../ai-companion/`. gadget no longer carries a `skills/` directory.
- **scripts/** — Ops + maintenance utilities: `sync.py` (centralized rclone data sync — push/pull/status, categories `summarize`/`website` (`tools/website/content` + `static` — the single Hugo content root)/`research`/`test` (benchmark data)/`backups` (force-regeneration backups) + special `dag`; all transfers use `rclone copy` — additive, never deletes; run as `python scripts/sync.py`; config `~/.config/gadget/sync.json`), `onboard.py` (one-time machine onboarding driven by a `tokens/onboard.yaml` sheet — SSH, Claude/Codex CLI auth, pip extras, per-tool config, rclone bootstrap; template `scripts/onboard.example.yaml`), `smoke.sh` (read-only smoke test across all tools), `serve_local_llm.sh` (set up the local Ollama LLM for summarize — creates a tuned Qwen3.6-35B variant and prints env to use; `eval "$(bash scripts/serve_local_llm.sh env)"`), `wsl_local_llm_cleanup.sh`, `audit_content_languages.py` (audit/fix bilingual Hugo content), `fix_report_languages.py`, `profile_translation.py` (translation-engine GPU profiler).

## Cross-Module Dependencies

`common/` provides shared infrastructure. Two re-export shims exist for backward compat:

```
common/ (canonical, pip-installed):
├─ io.py          — atomic_write, content_hash, load_json_config
├─ cache.py       — DiskCache
├─ json_utils.py  — parse_json_response, try_parse_json, repair_json_with_llm
├─ llm.py         — call_llm_raw, LLMCallConfig, call_llm, chunking/merge
├─ engine.py      — TranslationEngine, create_engine, OllamaEngine (default), TransformersEngine, VLLMEngine, LlamaCppEngine (GGUF)
├─ translation.py — translate_markdown_document, detect_language, build_translation_prompt
├─ bilingual.py   — write_bilingual (used by summarize, research, website)
└─ hugo.py        — run_hugo_update

summarize/llm_backends.py  ──re-exports──→  common.llm + common.json_utils
summarize/daily_summary.py ──imports──→     common.io + common.llm + common.json_utils + common.hugo (re-export shim)
summarize/formatter.py     ──imports──→     common.bilingual.write_bilingual
summarize/auto.py          ──subprocess──→  python -m summarize {daily,weekly,monthly} (no direct imports)
summarize/charts.py        ──imports──→     matplotlib (optional)
summarize/monthly_summary.py ──imports──→   config + common/ (via llm_backends shim)
summarize/weekly_summary.py  ──imports──→   monthly_summary.py + config + common/*
research/cache.py          ──re-exports──→  common.cache.DiskCache
research/llm.py            ──imports──→     common.llm.call_llm_raw + common.json_utils
research/scout/report.py   ──imports──→     common.bilingual.write_bilingual
research/research_scout.py ──imports──→     scout/ subpackage (backward-compat shim)
research/cli.py            ──imports──→     common.hugo
website/translate_content.py     ──imports──→  common.engine + common.translation
website/translate_site_batch.py  ──imports──→  common.engine + common.translation (incremental bilingual sync with state tracking)
```

Config resolution order (used by all tools): CLI flag > environment variable > `config.json` > hardcoded default.

## Translation Architecture

All bilingual content (daily/weekly/monthly reports, research reports, website pages) uses local batch inference (Ollama by default; vLLM on Linux, transformers on Windows, or llama.cpp GGUF as alternatives) instead of cloud LLM APIs. The pipeline:

1. `common.bilingual.write_bilingual()` — detects source language, writes original + translated .md/.zh.md pair
2. `common.translation.translate_markdown_document()` — translates full Hugo markdown preserving frontmatter, shortcodes, code blocks via collect-then-batch pipeline
3. `common.engine.create_engine()` — factory that auto-selects a backend implementing the `TranslationEngine` ABC (`load()`, `generate_batch()`, `unload()` lifecycle): `OllamaEngine` (auto-preferred when the Ollama tag is pulled), `VLLMEngine` (Linux), `TransformersEngine` (Windows), or `LlamaCppEngine` (GGUF — fast, low-memory, no PyTorch). A `_CachedEngineProxy` keeps a loaded engine warm across calls.

Default model: `tencent/Hy-MT2-1.8B` (GGUF variant `tencent/Hy-MT2-1.8B-GGUF`). Override via `GADGET_TRANSLATION_MODEL` env var or `--model` CLI flag. Backend override: `GADGET_TRANSLATION_BACKEND` (`ollama` / `vllm` / `transformers` / `llamacpp`). Batch size: `GADGET_TRANSLATION_BATCH_SIZE`. Ollama-path performance knobs: `GADGET_TRANSLATION_CONCURRENCY` (concurrent chunk requests, default 4 ≈ 2.2× wall-clock; `1` = sequential), `OLLAMA_TRANSLATION_NUM_CTX` (default 8192 — keeps HY-MT2 at ~3.6GB so it **co-resides** with the 24GB chat model instead of evicting it; zh chunks are capped at 5000 chars via `translation.chunk_ceiling` to fit), `OLLAMA_KEEP_ALIVE` (request-level residency, default `30m`). All Ollama base-URL defaults use `127.0.0.1`, not `localhost` (Windows resolves localhost IPv6-first → ~2s stall per request). `write_bilingual` stamps a `gadget:src-hash` marker into translated files and skips re-translation when the source is unchanged.

`website/translate_site_batch.py` adds **incremental state tracking** (`.translation_state.json`) to avoid re-translating unchanged files. It also handles fragment protection (code blocks, URLs, Hugo shortcodes preserved via placeholder tokens) and intelligent chunking for large documents.

## Tests

No repo-wide test runner; suites live per-module and run with `pytest` (all need `pip install -e .` so `common` and the tool packages import). Baseline suite is pure-mock — no network, GPU, or API keys:

```bash
pytest common/tests                        # Engine backends (ollama/budget), LLM dispatch
pytest scripts/tests                       # onboard.py (conftest inserts scripts/ on sys.path)
cd tools && pytest summarize/tests research/tests translator/tests/test_core.py
pytest tools/summarize/tests/test_config.py  # Single test file
```

Tests use `unittest.mock` to stub model loading, inference, and LLM backends. `summarize/tests/test_imports.py` parametrically verifies the re-export shim contract after refactoring. `research/tests/` mocks `call_scout_llm` and exercises the real `_screen_papers`/`_deep_evaluate_papers` pipeline functions (rather than re-implementing their logic inline).

- **Live-env e2e**: `summarize/tests/test_daily_e2e.py` needs a running Ollama + translation model + local device logs; it **auto-skips** otherwise. Run with `eval "$(bash scripts/serve_local_llm.sh env)"` then `cd tools && python -m pytest summarize/tests/test_daily_e2e.py -v -s`.
- **Untested subsystems** (smoke coverage only): benchmark, website, research profiler + Stage 4/5, summarize weekly/monthly renderers, most of `common/` + `scripts/`. Changes there need a manual smoke run — `bash scripts/smoke.sh` at minimum.

See `docs/reference/development.md` § Tests & smoke for the full matrix and environment caveats.

## Key Dependencies

Optional-dependency extras in `pyproject.toml`: `summarize`, `research`, `benchmark`, `website`, `translation`, `translation-gguf`, and `all` (= summarize+research+benchmark+website).

summarize: anthropic or openai (`requirements.txt` provided). Optional: Node.js (for ccusage / `@ccusage/codex` token stats), matplotlib (for token usage charts).
research: arxiv, anthropic or openai, openreview-py (`requirements.txt` provided). Optional: PyMuPDF (PDF text extraction in detailed profiler / `--insight` mode). bioRxiv/PubMed use stdlib only.
benchmark: torch, numpy, pandas, plotly, tqdm (`requirements.txt` provided). Optional: threadpoolctl; pyopencl (OpenCL detection for `--info` only — gpu run path is cuda/mps/xpu).
website: Pillow (image processing), torch + transformers (translation). Optional: vLLM (Linux, faster batch inference), llama-cpp-python (GGUF backend).

## Notes

- `tokens/` directory is gitignored and holds API tokens/secrets — never commit its contents.
- Generated data/report outputs go to `outputs/` (gitignored), organized by type: `outputs/reports/`, `outputs/logs/`, `outputs/cache/`, `outputs/data/`, `outputs/backups/`. **Exception:** generated *website* content is written directly into the single Hugo content root `tools/website/content|static` (gitignored via `.gitignore` allowlists) alongside hand-written posts — ownership is tracked per-file via the `gadget_generated: true` frontmatter marker (`common/website_backup.py`). `outputs/reports/*` remains the canonical report archive; website files are a derived Hugo representation of it.
- **Environment variables**: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` for API access; `SUMMARIZE_LOGS_DIR` and `SUMMARIZE_REPORTS_DIR` to override default output paths; `SUMMARIZE_CONFIG` to point at an explicit summarize config file (beats the repo-local/home lookup — used for test isolation).
- **Config files**: summarize resolves `SUMMARIZE_CONFIG` env > repo-local `tools/summarize/config.json` (gitignored; `config --init` writes here) > `~/.config/summarize/config.json`; research uses `~/.config/research_scout/config.json` + `~/.config/research/config.json` — each created via the tool's `config --init`.

## Git Tracking Rules

See `.gitignore` for the full list. Never `git add` auto-generated content, rclone-synced data, build artifacts (`build/`), or deployment/theme repos under `website/`. See `website/CLAUDE.md` for the detailed allowlist of what should be tracked.

## Skills

All Claude Code skills now live in the separate **ai-companion** repo (`git@github.com:TzJ2006/ai-companion.git`, checked out at the sibling `../ai-companion/`) — both the generic AI-dev/methodology skills (ccplan, optimize, cchypothesis, repo-audit, repo-tidy, plus the `/idea`→`/ccedit` pipeline) and the former gadget domain skills (summarize, slurm-gpu, nature-benchmark, NIPS-2025-paper). gadget no longer has a `skills/` directory; install skills from `../ai-companion/` (see its `scripts/install.ts`).

## Agentic Workflow (AI Dev Companion)

This repo follows the AI Dev Companion pipeline. All AI agents must read `AGENTS.md` before taking action.

- **Pipeline:** `/idea` → `/ccdiscuss` (align) → `/ccplan` (plan; STOPS for approval) → `/ccedit` (DAG execution) → `/ccdebug` (on failure). Use `/cconboard` to onboard existing code.
- **Plans (ECL):** live in `docs/ecl/*.yaml` — planning doc, execution DAG, and feature guards in one schema.
- **Change tracking:** a PostToolUse hook records `.py`/`.ts` edits at function level (and `.yaml`/`.md` at file level) into `.devcompanion/`.
- **Engine:** the **ai-companion** TypeScript monorepo (skills, hooks, exec/DAG runtime) — a *separate repo* (`git@github.com:TzJ2006/ai-companion.git`), checked out at the sibling `../ai-companion/`. See `../ai-companion/AGENTS.md` for internals.
- **Enforcement:** `.codex/hooks.json` (Codex) and `.claude/settings.json` (Claude Code, local) wire the change-tracking hooks to the sibling engine. (Re)install with `npx tsx ../ai-companion/scripts/install.ts . --enforce` after building ai-companion.

<!-- AI-DEV-COMPANION:START -->
## AI Dev Companion — Constraints

This project is tracked by AI Dev Companion. The following rules are enforced:

### Mandatory Workflows

1. **All code changes are automatically recorded** via PostToolUse hook — every Edit/Write to tracked files is captured
2. **Before starting a feature**, use `/ccplan` to create an ECL plan in `docs/ecl/`
3. **Before editing guarded files**, check `docs/ecl/*.yaml` for active feature guards and preserve invariants
4. **After editing**, the hook records: timestamp, file, tool, ECL context automatically
5. **When tests fail**, use `/ccdebug` — fix code, not tests (max 3 retries)
6. **For codebase analysis**, use `/cconboard` to generate structured documentation

### Tracked File Extensions

Changes to `.py`, `.pyi`, `.ts`, `.tsx`, `.mts`, `.cts` files are tracked at function level.

### Storage Layout

- `.devcompanion/queue/` — event queue (hook writes here, daemon processes)
- `.devcompanion/reviews/` — processed review sessions (JSON)
- `.devcompanion/history/` — per-file change history (JSON)
- `docs/ecl/` — active feature constraints (YAML, committed to git)

### Feature Guard Protocol

When `docs/ecl/*.yaml` files contain `feature_guard` sections:
- Before editing a guarded file, announce which invariants must be preserved
- After editing, run the guard's verification command
- If verification fails, revert and investigate — do not proceed with broken guards

### AI Dev Companion Location

- Install root: `D:\GitHub\ai-companion`
- Hook: `D:\GitHub\ai-companion/packages/hook/dist/index.js`
- Skills: `D:\GitHub\ai-companion/skills/`
<!-- AI-DEV-COMPANION:END -->
