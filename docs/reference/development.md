# Development Guide

Golden paths for extending gadget — the exact files to touch, the files to
leave alone, and the **silent failure** that hits if you miss a site (most of
these fail quietly, not loudly). Cited to `file:line`. Read `architecture.md`
first for the layering rules.

## The two import rules

1. **`common/` must never import from `tools/`.** The env-var bridge (`apply_env_from_config`) is the deliberate seam so `common/` stays tool-agnostic.
2. **No tool imports another tool.** Verified: zero cross-tool imports. Share via `common/`, or cross-tool orchestration via subprocess (`summarize/auto.py`), or read the other tool's config file. A tool that illegally imports another works under an editable install but breaks from repo root (`sys.path` shadowing) and violates the standalone contract.

---

## Golden paths ("add a new X")

### 1. Add a translation backend — the clean one ⭐

Localized to **`common/engine.py`**: add a `TranslationEngine` subclass
(template: the 4 existing classes — implement `load()`,
`generate_batch(prompts, *, max_new_tokens=4096)`, `unload()`), add the name to
`_TRANSLATION_BACKENDS` (`:724`), and add one `elif` in `create_engine()`'s
explicit-branch block (`:753-761`). Consumers call `create_engine()`
generically, so **no tool code changes**.

- For auto-selection: add an availability probe (pattern `_vllm_available` / `_llamacpp_available` / `_ollama_available`) + a branch in the auto chain (`:762-778`).
- For a **server-side** backend (no in-process GPU): add it to the `isinstance(eng, OllamaEngine)` VRAM-eviction gate at `:782` so it doesn't needlessly evict the Ollama chat model.
- **Loud failure**: an explicit `GADGET_TRANSLATION_BACKEND` value outside `_TRANSLATION_BACKENDS` raises `ValueError` before dispatch (`:735-738`); empty/unset still auto-selects.
- **Silent failure**: a name that IS in `_TRANSLATION_BACKENDS` but has no `elif` branch passes validation and falls into the auto-select chain, whose final else (`:776-778`) returns `TransformersEngine` — your new backend is silently never used.

### 2. Add an LLM chat backend

**`common/llm.py`** has **two** dispatch sites — edit **both**:
`call_llm_raw` (`:167`, dispatch `:179-186`, raw-text tier) and `call_llm`
(`:350`, dispatch `:353-360`, JSON tier), **plus** add the name to
`LLM_BACKENDS` (`:55`). Add an `elif` + a `_raw_<x>()` and a
`call_<x>(config)` impl (optionally a model-name map alongside `ANTHROPIC_MODELS`/`OPENAI_MODELS`) — ~5 edits.

Then add the name to the **9 argparse `choices=[...]` lists** gating `--api`:
`summarize/cli.py:47,68,123`; `research/scout/cli.py:850,856,889,909,923`;
`research/cli.py:157`.

- **Do not touch**: `research/llm.py` and `research/scout/evaluate.py` — they only delegate to `common.llm.call_llm_raw`.
- **Loud failure**: miss a dispatch `elif` (or misspell a backend anywhere — env, config `default_api`, `backend=` param) and the call raises `ValueError: Unknown LLM backend ...` naming `LLM_BACKENDS` (`:187`, `:361`) — the old silent `else → claude_cli` fallthrough is gone. Missing a `choices=` list is also loud (argparse hard-errors).
- **Residual quiet path**: config-file `default_api` values bypass argparse `choices` validation (they enter via `set_defaults`), so a bad config value only surfaces at the first LLM call — not at parse time — and the error names the value, not the config file it came from.

### 3. Add a summarize daily report field

Four anchors that must stay in sync by hand:

- `summarizer.py` — add to `SUMMARY_PROMPT` JSON + Requirements (`:39`, what ollama/openai/claude_cli obey) **and** `_daily_tool_schema()` properties/`required` (`:251`, what the anthropic backend obeys) **and** `CHUNK_MERGE_PROMPT` (`:165`, so days > 150K chars don't drop it during hierarchical merge). If overview-shaped, also `_OVERVIEW_FLAT_BLOCK`/`_REQ` (`:120-126`).
- `formatter.py` — render it in `generate_markdown()` (`:100`); if it's a level/importance list, add its key to `_sort_report_by_importance()` (`:34-35`).
- **Silent failures**: prompt-but-not-schema ⇒ field omitted on the anthropic path only (output differs by `--api`); schema-but-not-`generate_markdown` ⇒ field in JSON but never rendered; miss the sort key ⇒ unsorted; miss `CHUNK_MERGE_PROMPT` ⇒ dropped only on large days (passes small-day tests).
- **Cross-period**: adding to daily does **not** propagate to weekly/monthly — those have their own copy-pasted schemas/renderers (`weekly_summary.py`, `monthly_summary.py`) and strip fields in `format_reports_for_llm`. You must repeat the change there.

### 4. Add a config key

**summarize** (`config.py`) — three mechanisms depending on the key's job:

- CLI-default behavior → add to `_CLI_DEFAULTS_MAP` (`:84`, config-key → argparse dest), consumed by `cli_defaults()` (`:92`).
- Env-bridged knob (for `common/`) → add to `_ENV_FROM_CONFIG` (`:100`, config-key → env var), applied by `apply_env_from_config()` (`:110`).
- Output dir → just call `_resolve_output_dir(cli, env, config_key, default)` (`:53`) — no registry.

**research** (two files) — profiler keys in `config.py` `DEFAULT_CONFIG` (`:13`) at `~/.config/research/`; scout keys via `scout/config.py` `resolve_param` (`:86`) at `~/.config/research_scout/`.

- **Silent failures**: `_CLI_DEFAULTS_MAP` entry with no matching argparse dest ⇒ config silently ignored; `_ENV_FROM_CONFIG` uses `setdefault` so an already-exported env var overrides config; editing a non-active summarize config file (`~/.config` when a repo-local one exists, or either when the `SUMMARIZE_CONFIG` env var points elsewhere) does nothing; a scout key **must** be named `default_<param>` or `resolve_param` silently returns the hardcoded default; a key in the wrong research file (profiler vs scout) silently no-ops (except `default_api`, which `cmd_profile` cross-reads).

### 5. Add a whole new tool

- `pyproject.toml` — add an extra under `[project.optional-dependencies]` (`:8-16`); register the package in **both** `[tool.setuptools]` `package-dir` (`:19`) and `packages` (`:20`); add the extra to `all` (`:16`) if it should install with `.[all]`.
- Add `tools/<x>/__main__.py` exposing `main()` so `python -m <x>` works (pattern: existing tools' `__main__.py`).
- Add `tools/<x>/requirements.txt`, `CLAUDE.md`, `AGENTS.md`.
- Obey the two import rules above.
- **Silent failure**: omit the extra from `all` ⇒ `pip install -e ".[all]"` silently skips your deps (imports only work if the deps happen to be present).

---

## Tests & smoke

No repo-wide runner — run each suite (all need `pip install -e .` so `common`
and the tool packages import). Baseline suite (all pure-mock, no network/GPU/keys):

```bash
pytest common/tests
cd tools && pytest summarize/tests research/tests translator/tests/test_core.py
pytest scripts/tests
```

- **Package shadowing** (memory): run `python -m` from `tools/` if a stale root-level `summarize/`/`research/` dir ever reappears. `research/tests` self-inserts `tools/research` on `sys.path`; `scripts/tests/conftest.py` inserts `scripts/`.
- **conda AI env**: docs assume `conda activate AI`; the working env with `pytest` is on **WSL** (Windows-side base Miniconda lacks pytest). Don't use `conda run -n X` (crashes with a plugin error) — call the env python directly.
- **Live-env test**: `summarize/tests/test_daily_e2e.py` needs a running Ollama + translation model + local device logs; it **auto-skips** otherwise. Run with `eval "$(bash scripts/serve_local_llm.sh env)"` then `cd tools && python -m pytest summarize/tests/test_daily_e2e.py -v -s`.
- **Untested subsystems** (smoke only, no unit coverage): benchmark, website, research profiler + Stage 4/5, summarize weekly/monthly renderers, and most `common/` + `scripts/` modules. Changes there need a manual smoke run.

Fast safety net for any change: `bash scripts/smoke.sh` (read-only starts/parses).
