# Phase 0 Baseline Report

**Date:** 2026-07-01 · **Scope:** safety baseline — source-of-truth docs + a
read-only smoke net + a recorded test baseline. **No source code was modified.**

## What Phase 0 created

Paths shown are the current (post-tidy) locations; the four reference docs were
created at the repo root in Phase 0 and moved to `docs/reference/` afterward.

| File | Deliverable |
|---|---|
| `docs/reference/architecture.md` | repo architecture map (5 layers, hub-and-spoke, `common/` responsibilities, canonical model/backend facts) |
| `docs/reference/tools.md` | practical per-tool inventory (run command, config file, output paths, gotchas) |
| `docs/reference/debugging.md` | log/cache locations, config resolution, hidden side effects, stage-isolation recipes |
| `docs/reference/development.md` | golden paths for adding features + silent-failure warnings + test/smoke commands |
| `scripts/smoke.sh` | read-only smoke test (`--help`/`--info`/config-show/imports) |
| `docs/reports/phase0-baseline.md` | this report |

**Files modified (source):** none. Phase 0 is purely additive and reversible
(`git rm` the six files above). The stale facts in existing docs are **recorded**
below, not edited — that is Phase 1.

## Validation commands

Environment here: Windows, `D:\Miniconda3\python.exe` (Python 3.13.13),
`pytest 9.1.1`, a **live Ollama + translation stack reachable** (so the e2e test
ran instead of skipping).

```bash
# smoke net (read-only)
bash scripts/smoke.sh

# test baseline (run each suite; needs `pip install -e .`)
python -m pytest common/tests
cd tools && python -m pytest summarize/tests research/tests translator/tests/test_core.py
python -m pytest scripts/tests

# one-fact spot check
python -c "from common.engine import DEFAULT_TRANSLATION_MODEL; print(DEFAULT_TRANSLATION_MODEL)"  # -> tencent/Hy-MT2-1.8B
```

### Observed results (2026-07-01)

Initial baseline (before the post-Phase-0 hotfix below): `common` 13 pass;
`tools` 171 pass / **1 fail** (`test_daily_e2e`); `scripts` 7 pass; smoke 16 pass
/ 1 skip / 0 fail.

**After the hotfix (current):**

- `scripts/smoke.sh` — **16 passed, 1 skipped, 0 failed**. Skip = `benchmark --info` (`plotly` not installed in this bare env; install `pip install -e ".[benchmark]"`).
- `common/tests` — **13 passed**.
- `tools` suites — **175 passed, 0 failed** (e2e now passes; +3 new unit tests cover the fixes).
- `scripts/tests` — **7 passed**.

### Real pre-existing crash — found by Phase 0, hotfixed at user request

`test_daily_e2e` ran (not skipped — live Ollama + `2026-06-26` logs present) and
exposed genuine formatter brittleness against the local model's variable JSON.
Phase 0 recorded it; the user then approved a hotfix. Fixed (code change beyond
the Phase 0 doc scope, done deliberately after the baseline):

1. **`formatter.py` — list items assumed to be dicts.** `_render_task` used `t['name']` (hard subscript) → `KeyError` when a task lacked `name`; and `qwen3.6:35b` sometimes emits whole list fields (`conversation_summaries`, `tasks`, …) as **bare strings**, crashing the `.get()`-based renderers and the project grouping. Fixed with `_coerce_report_lists()` — a single trust-boundary normalizer that wraps bare strings under each field's natural key and drops junk, called before sort and render. `_render_task` also hardened to `t.get('name', 'N/A')`.
2. **`summarizer.py` — required `summary` key renamed by the model.** `qwen` unpredictably emits `one_sentence_summary` / `daily_summary` / other `*summary*` names, silently producing an empty report summary. Fixed with `_normalize_report()` at the `_call_summarize` chokepoint — recovers `summary` from a known synonym, else any top-level `*summary*` string field.

Verified: `test_daily_e2e` **4/4 green** across fresh live runs (previously failed
with 3 distinct output shapes); +3 unit tests in `test_summarizer.py` /
`test_formatter.py`. Not addressed: the *underlying* prompt-adherence variance —
these are defensive guards at the LLM→render boundary, not a prompt rework.

Memory note: the recorded facts "base conda has no pytest" and "AI env absent on
Windows" are now **stale** — this box has `pytest 9.1.1` and a reachable Ollama.

## Doc drift recorded (fix in Phase 1)

> **Status: all fixed in Phase 1 (2026-07-02).** See "Phases 1–4 — completion" below.

Verified against live code (`file:line`):

- `CLAUDE.md` translation model `HY-MT1.5-1.8B` → code is **`Hy-MT2-1.8B`** (`common/engine.py:19`; GGUF `:20`; Ollama tag `:24`). Stale throughout the doc.
- `CLAUDE.md` "three backends" → **four** (`OllamaEngine` at `common/engine.py:544` is missing, and it's the auto-preferred default).
- `common/__init__.py` `__all__` omits `OllamaEngine` and `LlamaCppEngine` (the default + low-mem backends).
- `pyproject.toml` still declares the dead `mcp[cli]>=1.0.0` base dependency though MCP was removed (CLAUDE.md itself says "no MCP integration").
- `research_scout.py:38` has a stale `mcp_server` comment (the file is a live deprecation shim, not dead).

## Remaining uncertainties (decide before later phases)

- ~~**Benchmark CSV canonicalization.**~~ **Resolved (Phase 1):** `tools/benchmark/benchmark_results.csv` is **not** an orphan — it is the documented canonical CSV for the *submission/ingest* pipeline (`ingest_submissions.py`, `submit_result.py`, `daily-publish.yml` all default to it; `benchmark/CLAUDE.md:110` + `docs/ecl/gadget-features.yaml:1521` deliberately separate it from the CLI's `outputs/data/benchmark/results.csv`). Kept. Only `tools/benchmark/data/benchmark_results.csv` (byte-identical duplicate) is a plausible stray — left in place (committed data, no proof it's unused; removal deferred pending owner confirmation).
- **MCP removal completeness.** `mcp[cli]` dep + stale comments remain; confirm nothing imports it before dropping the dep (Phase 1).
- **Research config merge.** Two config systems (profiler `~/.config/research/`, scout `~/.config/research_scout/`) with different key sets and a cross-read in `cmd_profile`. Decide whether to unify (Phase 4) or keep scoped.

## What Phase 0 does NOT solve

Phase 0 establishes a regression net + accurate docs. It deliberately does **not**:

- change any runtime behavior (including the `formatter.py:151` crash above — recorded, not fixed);
- correct the stale facts in existing docs (`CLAUDE.md`, `__init__.py`) — `docs/reference/architecture.md` becomes the new source of truth; **Phase 1** edits the drifted files;
- remove dead surfaces (`mcp[cli]`, stale comments, orphan CSVs) — **Phase 1**;
- add a backend registry or fix the silent `else → claude_cli` / unknown-translation-backend fallthroughs — **Phase 2**;
- add per-run context-header logging to make failures self-explaining — **Phase 2**;
- reduce duplication (per-period report schemas/renderers, two JSON parsers, split config systems, three-way benchmark schema) — **Phase 3**;
- split `common/engine.py`, fix the `_free_ollama_vram` hidden eviction or the model-id-keyed engine cache, or untangle scout/profiler — **Phase 4**;
- add unit coverage for the untested subsystems (benchmark, website, research profiler + Stage 4/5, weekly/monthly renderers) — smoke covers "starts and parses," not correctness.

## Phases 1–4 — completion (2026-07-02)

All four phases executed. Deterministic suite green throughout: **common 19, scripts 7,
tools 180 (e2e excluded), 0 failures**; smoke 16/1/0. Live e2e green across repeated runs
(1 transient merge timeout, environmental — not a code defect).

**Phase 1 — doc drift + dead surfaces.**
- Model name `HY-MT1.5-1.8B` → `Hy-MT2-1.8B` and backend count/default (three → four, Ollama
  default) fixed in root `CLAUDE.md`, `tools/website/CLAUDE.md`, `README.md` (incl. the flatly
  wrong "claude_cli（默认）" LLM line), `docs/reference/external-dependencies-inventory.md`.
- Dropped dead `mcp[cli]>=1.0.0` base dep from `pyproject.toml` (no `import mcp` anywhere).
- `common/__init__.py` `__all__` + imports now include `OllamaEngine`, `LlamaCppEngine`.
- Removed stale `mcp_server.py` comment in `research_scout.py`.
- *Left intentionally:* `docs/ecl/*` (companion-generated planning artifacts — regenerated, not
  hand-edited); benchmark submission CSV (see corrected uncertainty above).

**Phase 2 — backend dispatch correctness.** Silent `else → claude_cli` fallthroughs in
`call_llm_raw`/`call_llm` and the unknown-`GADGET_TRANSLATION_BACKEND` → auto-select fallthrough
in `create_engine` now raise `ValueError` naming the valid set (shared `LLM_BACKENDS` /
`_TRANSLATION_BACKENDS` constants — the lightweight "registry"; a dict-of-callables would be
indirection for 4 entries). Empty `GADGET_LLM_BACKEND` falls back to `ollama`. Added debug-level
dispatch context logging. Verified no live caller passes a backend outside the valid set.

**Phase 3 — dedup.** Only one genuine, low-risk consolidation taken: `research/llm.py`'s
escalating JSON-repair ladder now delegates to `common.repair_json_with_llm(strategy="escalating")`
(added a `max_chars` param, default 5000, so the profiler keeps its 20K cap) — removes a duplicate
haiku→sonnet→opus ladder. *Declined (documented):* per-period report renderers (genuinely
different schemas, no unit coverage → high regression risk), the two research config systems
(scoped by design; Phase 4 "decide" item — kept scoped), the three-way benchmark schema
(intentional submission-vs-CLI separation — see Phase 1). Consolidating those is over-engineering.

**Phase 4 — real fixes, skipped re-orgs.** Engine cache re-keyed by `(backend, model_id)` (was
`model_id`-only → returned an engine for the wrong backend when the backend env changed
mid-process); type annotation corrected to match. Added `GADGET_KEEP_OLLAMA=1` opt-out so
`_free_ollama_vram()` no longer force-evicts the resident chat model (the fix its own comment
sign-posted). *Declined (documented):* splitting `common/engine.py` and "untangling"
scout/profiler — large diffs for organizational-only benefit, high regression risk, no functional
gain; not done.

**Tests added:** `common/tests/test_dispatch.py` (backend validation), `+2` engine tests
(composite cache key, keep-ollama gate), `research/tests/test_llm_parse.py` (repair delegation),
`+3` summarizer tests (envelope unwrap + renamed-top-vs-decoy), `+2` formatter tests (prior).

**Adversarial verification.** A 3-agent read-only review found one **medium** defect that tests
missed: `_unwrap_envelope` could unwrap to a thin decoy sub-object (e.g. `statistics.summary`) and
silently discard a top-level report whose keys were merely renamed. Fixed: the "already the real
report?" check now counts summary synonyms (not just 4 exact keys), and unwrap picks the *richest*
child; covered by new tests. The dispatch and cache/eviction changes reviewed clean.
