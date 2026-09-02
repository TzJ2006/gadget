# gadget — Agent Guide

Python 3.10+ toolkit of five standalone tools — AI conversation reports (`summarize`), paper discovery (`research`), CPU/GPU benchmarking (`benchmark`), a Hugo blog with automated publish (`website`), and a Gradio document translator (`translator`) — sharing one infrastructure package `common/` (LLM calls, JSON repair, disk cache, atomic IO, local-inference translation, Hugo deploy). License is GPL-3 (`LICENSE`). Everything installs editable via `pip install -e .` from `pyproject.toml`; each tool has its own optional-dependency extra. `pip install -e ".[all]"` is summarize + research + benchmark + website only — translator is **not** in `[all]` (`pip install -e ".[translator]"`). The dev workflow engine and skills live in the separate sibling repo `../ai-companion/`, wired in via Edit/Write hooks; plans/decisions persist as ECL YAML under `docs/ecl/`. Human usage is in `TUTORIAL.md`; this file is the agent protocol.

## Commands

```bash
pip install -e ".[all]"        # common + summarize/research/benchmark/website extras; does NOT include translator
pip install -e ".[translator]" # Gradio GUI extra (gradio + translation-gguf); not part of [all]
bash scripts/smoke.sh          # read-only smoke net across all tools (--help/--info/imports; no LLM, network, or writes)

# Tests — per-module pytest suites, no repo-wide runner; baseline suites are pure-mock (no network/GPU/keys)
python -m pytest common/tests scripts/tests
cd tools && python -m pytest summarize/tests research/tests website/tests translator/tests/test_core.py
python -m pytest tools/summarize/tests/test_config.py                # single file
python -m pytest tools/summarize/tests/test_config.py::test_name -v  # single test

# Run (details + verification in each tool's AGENTS.md, including tools/translator/AGENTS.md)
python -m summarize auto --deploy                     # daily → weekly → monthly reports + Hugo deploy
python tools/research/research_scout.py report --project my-project
cd tools/benchmark && python -m benchmark.cli         # must cd into tools/benchmark first
cd tools/website && bash update.sh                    # Windows: powershell -ExecutionPolicy Bypass -File tools/website/update.ps1
python -m translator                                  # Gradio GUI (blocks until closed); see tools/translator/AGENTS.md
python scripts/sync.py push|pull|status               # rclone cross-device data sync
```

No linter/formatter is configured (no ruff/black/flake8 config) — match the existing style.

## Architecture

```text
common/           Shared pip package: llm.py (4 backends), engine.py (translation engines), translation.py,
                  bilingual.py, hugo.py, cache.py, json_utils.py, io.py, config.py, paths.py, site_staging.py,
                  website_backup.py; tests in common/tests/
tools/summarize/  Daily/weekly/monthly AI-conversation reports (unified CLI: python -m summarize)
tools/research/   Paper discovery + researcher profiling + citation graph (scout/ package, apis/ clients)
tools/benchmark/  CPU/GPU FLOPS benchmark (benchmark/ package, append-only benchmark_results.csv)
tools/website/    Hugo blog (PaperMod), media compression, bilingual translation, GitHub Pages deploy
tools/translator/ Gradio translator GUI over common.engine (core.py logic, app.py UI); see tools/translator/AGENTS.md
scripts/          Ops: sync.py (rclone), onboard.py (machine setup), smoke.sh, serve_local_llm.sh,
                  profile_translation.py, language.py; tests in scripts/tests/
docs/             Design docs, docs/ecl/ plans, docs/reference/ deep dives (architecture, development, debugging)
outputs/          All generated artifacts (gitignored): logs/ reports/ cache/ data/ images/ backups/
tokens/           API keys + onboarding sheet (gitignored — never commit or quote)
```

Rules of the layering (see `docs/reference/architecture.md`): hub-and-spoke — shared code lives in `common/`, **no tool imports another tool** (cross-tool only via subprocess or reading config), and `common/` never imports from `tools/`. Backward-compat re-export shims must stay alive: `research/cache.py`, `research/research_scout.py`.

Config file is repo-root `config.json` only (gitignored; template `config.example.json`). Override the path with `GADGET_CONFIG`. No `~/.config/...` or `tools/<tool>/config.json` fallback. Setting resolution: CLI flag > environment variable > that file's namespaced section (`summarize` / `research` / `research_scout` / `sync` / `translator`) > hardcoded default. LLM backend is switched uniformly via `--api`: `ollama` (default, keyless local) / `claude_cli` / `anthropic` / `openai` (global override `GADGET_LLM_BACKEND`). Translation is local inference only — `common.engine.create_engine()` auto-picks Ollama / llama.cpp GGUF / vLLM / transformers (override `GADGET_TRANSLATION_BACKEND`). The Ollama path translates with the served chat tag (`gemma4:26b`); the in-process fallbacks use `tencent/Hy-MT2-1.8B`, auto-downloaded on first run.

## Conventions

- PEP 8, 4-space indent, `snake_case` functions, `PascalCase` classes, `UPPER_CASE` constants; typed Python with `pathlib.Path`.
- Tests live next to their module in `tests/` (`common/tests`, `scripts/tests`, `tools/<tool>/tests`) as `test_*.py`; heavy deps (models, LLM APIs) stubbed with `unittest.mock`.
- Generated artifacts go to `outputs/` — with one exception: generated website content is written directly into `tools/website/content|static`, stamped with `gadget_generated: true` frontmatter. Files without that marker are human-written and must never be overwritten (raises `HumanContentError`).
- Docs are bilingual: English at root (`README.md`, `TUTORIAL.md`), Chinese in `docs/` (`README.zh.md`, `TUTORIAL.zh.md`); Hugo content pairs `file.md` / `file.zh.md`.
- Never `git add` generated content, synced data, `build/`, `gadget.egg-info/`, or the deploy/theme repos under `tools/website/`.

## Gotchas

- Benchmark commands must be run from `tools/benchmark/` (paths are cwd-relative); results **append** to `benchmark_results.csv` by design — never rewrite or dedupe it.
- Ollama base URLs default to `127.0.0.1`, never `localhost` — Windows resolves localhost IPv6-first, adding a ~2s stall per request (`common/llm.py`, `common/engine.py`).
- `test/` at the repo root is a gitignored experiment sandbox, **not** a pytest suite; the benchmark tool is `tools/benchmark/`.
- `tools/website/public/` is a separate deployment git repo (`tzj2006/tzj2006.github.io`) committed and pushed by the update scripts — never commit into it manually.
- `tools/summarize/tests/test_daily_e2e.py` needs a live Ollama + local device logs; it auto-skips otherwise.
- `pip install -e .` drops `build/` and `gadget.egg-info/` at the repo root — gitignored build artifacts, leave them alone.
- `config.json` and `tokens/` hold secrets (gitignored) — never commit, and never quote their contents into docs or logs.
