# CLAUDE.md

> **Workflow**: This module follows the agentic protocol in [`AGENTS.md`](AGENTS.md) — AI Dev Companion pipeline; plans live in `../../docs/ecl/*.yaml`.

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Cross-platform CPU/GPU benchmarking tool with a submission pipeline for crowdsourced hardware data. Measures FLOPS via scalar loops (CPU single-core) and GEMM matrix multiplication (CPU BLAS, GPU). Results accumulate in a CSV file; an interactive HTML report is generated with Plotly.

## Key Commands

```bash
# Run all benchmarks (results append to CSV)
python -m benchmark.cli

# CPU or GPU only
python -m benchmark.cli --cpu-only
python -m benchmark.cli --gpu-only

# Run + generate HTML report
python -m benchmark.cli --report

# Run + report + deploy to Hugo website
python -m benchmark.cli --report --deploy

# Generate report from existing CSV (no benchmarks)
python -m benchmark.cli --report-only

# Show system info only
python -m benchmark.cli --info

# Quick validation (short duration, no CSV save)
python -m benchmark.cli --cpu-only --matrix-size 1024 --duration 1 --no-save

# Custom duration per test (default: 10 seconds)
python -m benchmark.cli --duration 60

# Custom output paths
python -m benchmark.cli --output my_results.csv
python -m benchmark.cli --report-only --input-csv my_results.csv --report-output report.html
```

### Upload to Public Leaderboard

```bash
# Interactive prompt after benchmark (requires relay URL)
python -m benchmark.cli --relay-url https://relay.example.com/submit

# Non-interactive upload
python -m benchmark.cli --upload --relay-url https://relay.example.com/submit

# Via environment variable
export BENCHMARK_RELAY_URL=https://relay.example.com/submit
python -m benchmark.cli

# Disable upload flow
python -m benchmark.cli --no-upload
```

### Submission Scripts

```bash
# Dry-run preview of latest CSV row
python scripts/submit_result.py --dry-run

# Submit to relay endpoint
python scripts/submit_result.py --relay-url https://relay.example.com/submit

# Direct GitHub dispatch
python scripts/submit_result.py --github-owner ORG --github-repo REPO --github-token $TOKEN

# Ingest queued submissions into CSV
python scripts/ingest_submissions.py \
  --pending-file data/pending_submissions.ndjson \
  --csv-path benchmark_results.csv
```

## Default Parameters

- **Output paths**: CSV → `outputs/data/benchmark/results.csv`, HTML → `outputs/reports/benchmark/report.html` (relative to gadget project root)
- **Duration**: 10 seconds per benchmark
- CPU single-core: 10,000,000 scalar iterations (sqrt + add)
- CPU BLAS: matrix_size 2048 (single-core), 4096 (all-cores)
- GPU: matrix_size 8192 (auto-sized by GPU memory), 50 iterations

## Architecture

```
benchmark/                  # Project root
├── benchmark/              # Python package
│   ├── cli.py              # Entry point, argparse, upload flow, deploy orchestration
│   ├── core.py             # BaseBenchmark ABC, RobustTimer, BenchmarkResults (CSV append)
│   ├── cpu.py              # CpuSingleCoreBenchmark (scalar), CpuAllCoresBenchmark (BLAS GEMM)
│   ├── gpu.py              # GpuBenchmark (CUDA/MPS/XPU, multi-dtype)
│   ├── detect.py           # get_cpu_info(), get_gpu_info(), get_system_info()
│   ├── report.py           # BenchmarkReport — HTML generation with Plotly charts
│   └── publish.py          # stage_benchmark_report() — Hugo staging via common.site_staging
├── scripts/
│   ├── submit_result.py    # Submit CSV row to relay endpoint or GitHub dispatch
│   └── ingest_submissions.py  # Validate/dedupe/sanitize NDJSON queue → append CSV
├── data/                   # Queue/audit files for submission pipeline
│   ├── pending_submissions.ndjson
│   ├── rejected_submissions.ndjson
│   └── ingest_log.json
├── .github/workflows/      # CI/CD
│   ├── accept-submission.yml   # Receives repository_dispatch → appends to pending queue
│   ├── daily-publish.yml       # Daily: ingest queue → regenerate report → commit
│   └── pages-deploy.yml        # Deploy benchmark_report.html to GitHub Pages
└── benchmark_results.csv   # Legacy/root-level CSV (scripts default to this path)
```

### Data Flow

Two independent paths feed the CSV:

1. **Local run**: `cli.py` → benchmarks → `BenchmarkResults.save()` → CSV append
2. **Submission pipeline**: `submit_result.py` → relay/dispatch → `accept-submission.yml` → `pending_submissions.ndjson` → `ingest_submissions.py` (validate, sanitize PII, SHA-256 fingerprint dedupe) → CSV append → `daily-publish.yml` regenerates report

### Key Design Decisions

- **CSV append-only**: Never overwrites. Each run appends rows. Report reads all history for leaderboards and trend charts.
- **Project root resolution**: `cli.py` computes `_PROJECT_ROOT` as two levels up from itself (`benchmark/benchmark/cli.py` → `gadget/`). Default output paths are under `gadget/outputs/`.
- **Hugo deploy**: `--deploy` flag calls `publish.stage_benchmark_report()` which copies the HTML to `tools/website/static/benchmark-report/` and writes the `content/benchmark.md` wrapper page (stamped `gadget_generated: true`), then triggers `common.hugo.run_hugo_update()`.
- **Upload flow**: After a saved benchmark run, the CLI may prompt for upload (interactive) or auto-upload (`--upload`). Upload calls `scripts/submit_result.py` as a subprocess. Upload failures never fail the benchmark run.

## Measurement Methodology

1. **Warmup**: 5–100 iterations (type-dependent)
2. **Measurement**: 5–50 iterations within `--duration` window
3. **Statistics**: Median time with IQR-based outlier removal (`RobustTimer`)
4. **GPU sync**: Explicit `torch.cuda.synchronize()` / `torch.mps.synchronize()` before timing
5. **FLOPS**: Scalar = `2 * iterations`, GEMM = `2 * N^3 * iterations`

## Platform & dtype Support

| Backend | FP64 | FP32 | FP16 | BF16 | FP8_exp |
|---------|------|------|------|------|---------|
| CUDA    | yes  | yes  | yes  | yes (8.0+) | yes (8.9+, experimental) |
| MPS     | no   | yes  | yes  | no   | no      |
| XPU     | yes  | yes  | yes  | yes  | no      |

MPS (Apple Silicon) does not support FP64 or BF16. FP8 matmul is not fully supported in PyTorch yet.

## Adding a New Benchmark

1. Subclass `BaseBenchmark` from `core.py`
2. Implement `get_info()` → dict, `run_iteration()` → timing result, `get_flops()` → float
3. Add to `cpu.py` or `gpu.py` (or new module)
4. Wire into `cli.py` main loop and add to the `run_all_*_benchmarks()` function

## Submission Ingestion Validation

`ingest_submissions.py` enforces:
- All 20 CSV columns present
- `backend` in `{cpu, cuda, mps, xpu, opencl, ocl}`
- `benchmark_type` in `{gpu, cpu_single_core, cpu_single_core_blas, cpu_all_cores}` (or `cpu_*` prefix)
- Numeric ranges (e.g., `cpu_cores` 1–2048, `flops_gflops` > 0, `time_seconds` < 3600)
- PII sanitization: emails, IPs, hostnames, user paths redacted
- SHA-256 fingerprint deduplication (keyed on date + hardware + benchmark type + results)

## Commit Style

Short imperative messages scoped by area: `gpu: improve FP16 timeout handling`, `report: add trend chart`.

## Dependencies

**Required**: torch, numpy, pandas, plotly, tqdm. **Optional**: threadpoolctl (BLAS thread control), pyopencl (Intel/AMD GPU fallback). Install via `pip install -r requirements.txt`.
