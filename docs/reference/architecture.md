# Architecture Map

gadget is a Python 3.10+ utility monorepo (~26k LOC): five standalone tools on
one shared foundation. This is the **source-of-truth** map — where any other doc
disagrees with code, code wins (drift list at the bottom). Every fact below is
cited to `file:line`.

## The one rule: hub-and-spoke

All shared code lives in `common/`. **No tool imports another tool** (verified:
zero cross-tool imports across `tools/`). Tools interact only by:

- **subprocess** — e.g. `summarize/auto.py` shells out to `python -m summarize {daily,weekly,monthly}`;
- **reading another tool's config file** — e.g. research `cmd_profile` falls back to the scout config for `default_api`.

`common/` must **never** import from `tools/`.

```
                       common/   (pip-installed foundation)
                    ▲    ▲    ▲    ▲    ▲
        ┌───────────┘    │    │    │    └───────────┐
    summarize        research  benchmark  website  translator      scripts/
     (tools/* — independent spokes, no tool → tool imports; common/ is the only hub)
```

## Layers

L1 pure utilities → L2 infrastructure adapters → L3 shared services → L4 tool
domain logic → L5 CLI/orchestration. Lower layers never import upward.

| Layer | Module | Responsibility |
|---|---|---|
| **L1** pure util | `common/paths.py` | canonical output-dir constants: `GADGET_ROOT`, `OUTPUTS_DIR`, `REPORTS_DIR`, `LOGS_DIR`, `CACHE_DIR`, `DATA_DIR`, `IMAGES_DIR` |
| | `common/io.py` | `atomic_write`, `content_hash`, `load_json_config` |
| | `common/json_utils.py` | `parse_json_response` / `try_parse_json` + repair (LLM-output tolerant; `repair_json_with_llm` may itself call an LLM) |
| | `common/cache.py` | `DiskCache` — SHA-256 keyed, namespaced, TTL |
| **L2** infra adapter | `common/llm.py` | unified LLM layer (raw text + JSON) over ollama / anthropic / openai / claude-cli + chunking & hierarchical merge |
| | `common/engine.py` | `TranslationEngine` ABC + 4 backends + `create_engine()` factory |
| | `common/hugo.py` | `run_hugo_update` — shells out to Hugo, cross-platform |
| | `common/site_staging.py` | write generated Hugo content/static directly into the Hugo site (`resolve_site_staging_root(hugo_site) == hugo_site`; default `tools/website`); stamps `gadget_generated: true`, blocks human-file overwrites (`common/website_backup.py`) |
| **L3** shared service | `common/translation.py` | `translate_markdown_document` — chunking, fragment protection, frontmatter preservation |
| | `common/bilingual.py` | `write_bilingual` — detect source language, write `.md` + `.zh.md` pair |
| **L4** tool logic | `tools/{summarize,research,benchmark,website,translator}/` | see `tools.md` |
| **L5** CLI / ops | each tool's `__main__.py`/`cli.py`; `scripts/` | argument parsing, orchestration, ops utilities |

## Canonical model/backend facts (from code, not docs)

The facts other docs most often get wrong. Verified against source:

- **Default chat backend** — `ollama`. `common/llm.py:53` `DEFAULT_BACKEND = os.environ.get("GADGET_LLM_BACKEND") or "ollama"` (the `or` form, so an exported-but-empty env var still falls back to ollama). Default served chat tag `gemma4:26b` (`llm.py:62`). Override per-call, via `--api`, or globally via `GADGET_LLM_BACKEND`.
- **Chat backends** — `ollama` (default), `anthropic`, `openai`, `claude_cli` (single source of truth: `LLM_BACKENDS`, `llm.py:55`). Dispatched in `common/llm.py` by `call_llm_raw` (`:167`) and `call_llm` (`:350`); unknown values raise `ValueError`.
- **Default translation model** — Ollama path (the default backend) translates with the chat tag `gemma4:26b` (`common/engine/base.py`, `DEFAULT_TRANSLATION_MODEL_OLLAMA = DEFAULT_OLLAMA_CHAT_MODEL`); resolution is `OLLAMA_TRANSLATION_MODEL` > `OLLAMA_MODEL` > that default, so translation follows whatever chat tag is served instead of loading a second runner. In-process fallbacks (vllm/transformers/llamacpp, only reached when Ollama is unreachable) stay on the dedicated MT model `tencent/Hy-MT2-1.8B` / GGUF `tencent/Hy-MT2-1.8B-GGUF`.
- **Translation backends — FOUR** (`common/engine.py`): `OllamaEngine` (`:544`, auto-preferred when a local Ollama has the model pulled), `VLLMEngine` (`:376`, Linux batch), `TransformersEngine` (`:189`, Windows default), `LlamaCppEngine` (`:454`, GGUF low-memory, no PyTorch). ABC `TranslationEngine` at `:146`; factory `create_engine()` at `:727`; `shutdown_engines()` at `:789`. (Docs said "three backends" — fixed in Phase 1.)
- **Translation backend selection** — `GADGET_TRANSLATION_BACKEND` explicit override (unknown non-empty value raises), else auto-detect `ollama → vllm → llamacpp → transformers` (`engine.py:734-778`). Model id: `resolve_translation_model` = arg > `GADGET_TRANSLATION_MODEL` > default (`engine.py:88-93`). Engine cache keyed by `(backend, model_id)`.

## `common/` facade caveat

`common/__init__.py` `__all__` re-exports all four engines including
`OllamaEngine` and `LlamaCppEngine` (added in Phase 1 — previously omitted). Any
engine can be imported from `common` or from `common.engine` directly.

## Config resolution (all tools)

Uniform contract, per-tool implementation: **CLI flag > env var > config.json >
hardcoded default** (`summarize/config.py:53-68`; `research/scout/config.py:86-94`).
See `debugging.md` for exact env vars and config-file locations.

## Doc drift (recorded here, all fixed in Phase 1 — see `docs/reports/phase0-baseline.md`)

- `CLAUDE.md`: `HY-MT1.5-1.8B` → `Hy-MT2-1.8B`; "three backends" → four (add `OllamaEngine`). ✅
- `pyproject.toml` dropped the dead `mcp[cli]` dependency. ✅
- `common/__init__.py` `__all__` now includes `OllamaEngine` + `LlamaCppEngine`. ✅
