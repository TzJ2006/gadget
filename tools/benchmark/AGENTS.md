# AGENTS.md — benchmark module

> **Workflow Protocol**: Follow [../../AGENTS.md](../../AGENTS.md) — AI Dev Companion pipeline (/ccdiscuss → /ccplan → /ccedit → /ccdebug; plans in `../../docs/ecl/*.yaml`).
> Paraphrase the task and get explicit confirmation before editing code.

## Module Scope

- `benchmark/` Python package: `cli.py`, `cpu.py`, `gpu.py`, `detect.py`, `core.py`, `report.py`, `publish.py`
- `data/` — submission queue/audit (`pending_submissions.ndjson`, etc.); CSV SoT is `benchmark_results.csv` (CLI + ingest + CI)
- `scripts/` — ingestion and submission utilities
- `results/` — historical GPU speed test images

## Verification Commands

Use these to verify changes to this module:

```bash
cd tools/benchmark && python -m benchmark.cli --cpu-only --duration 3   # CPU smoke test
cd tools/benchmark && python -m benchmark.cli --report-only             # Report generation
cd tools/benchmark && python -m benchmark.cli --info                    # System info check
```

## Coding Conventions

- PEP 8, 4-space indent, `snake_case` functions, `PascalCase` classes, `UPPER_CASE` constants
- Benchmark payloads as explicit dicts with stable keys (`dtype`, `backend`, `flops_per_sec`)
- Small composable functions in `benchmark/` — no inline logic in CLI handlers

## File Conventions

| Purpose | Location |
|---------|----------|
| Plans / ECL | `../../docs/ecl/*.yaml` |
| Change tracking | `../../.devcompanion/` |
