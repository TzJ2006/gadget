# tools/research

Paper discovery (scout) and researcher profiling (profiler), plus the API clients they share.

| Piece | Entry | Code |
|---|---|---|
| Scout | `python -m research.scout` | `scout/` |
| Profiler | `python -m research` | package root |
| API clients | imported by both | `apis/` |

`python tools/research/research_scout.py` is a deprecation shim for the scout CLI. Leave it in place.

Guides: [TUTORIAL.md](TUTORIAL.md), [SUMMARY.md](SUMMARY.md), [AGENTS.md](AGENTS.md).

## Which files are which

Scout config and prompts are `scout/config.py` and `scout/prompts.py`. Scout stages live in `scout/` (`search.py`, `evaluate.py`, `report.py`, `insight.py`, `ask.py`, `cli.py`, `project.py`).

Package-root `config.py`, `prompts.py`, and `llm.py` are the profiler, along with `cli.py`, `models.py`, `scoring.py`, `analysis.py`, `student_discovery.py`, `homepage_discovery.py`, and `output.py`. `llm.py` is a profiler wrapper. The shared client is [`common/llm.py`](../../common/llm.py).

`apis/` holds `arxiv_client.py`, `semantic_scholar.py`, `openreview_client.py`, and `rate_limiter.py`.

## Shims

- `research_scout.py` — old CLI path. Real commands are `python -m research.scout`.
- `cache.py` — re-exports `common.cache.DiskCache`.

## Reports

[reports/README.md](reports/README.md) is a tombstone. Real scout reports go to `outputs/reports/research-scout/`.

## Where new files go

- Scout behavior: `scout/`.
- Profiler behavior: this directory, next to `cli.py`.
- A new paper API: `apis/`.
- Tests: `tests/`.
- Do not write reports under `reports/`.
