# tools/benchmark — CPU/GPU FLOPS Benchmark

Cross-platform floating-point benchmark for NVIDIA (CUDA) / Apple Silicon (MPS) / Intel (XPU) across FP64–FP8 precisions. Logic lives in the `benchmark/` package (`cli.py`, `core.py`, `cpu.py`, `gpu.py`, `detect.py`, `report.py`, `publish.py`); `benchmark_results.csv` is the append-only source of truth, `data/` holds the leaderboard submission queue, `scripts/` the ingest/submit utilities.

## Commands

All commands must run from this directory (`cd tools/benchmark`). Deps: `pip install -e ".[benchmark]"` from repo root (torch, numpy, pandas, plotly, tqdm).

```bash
python -m benchmark.cli                          # run all benchmarks (appends to CSV)
python -m benchmark.cli --cpu-only --duration 3  # quick CPU smoke (default duration 10s)
python -m benchmark.cli --gpu-only
python -m benchmark.cli --info                   # hardware detection only, no CSV write
python -m benchmark.cli --report-only            # HTML report from existing CSV
python -m benchmark.cli --report --deploy        # run + report + publish to Hugo /benchmark/
```

## Quirks

- No pytest suite — verify changes with `--info`, `--cpu-only --duration 3`, and `--report-only`.
- `import benchmark` pulls in `report.py` → plotly, so even `--info` fails with ModuleNotFoundError until the `benchmark` extra is installed.
- GPU run path is cuda/mps/xpu only; OpenCL appears in `--info` detection but is never benchmarked.
- The CSV is append-mode by design (multi-hardware accumulation leaderboard) — never overwrite, dedupe, or sort it in place.
- Benchmark payloads are explicit dicts with stable keys (`dtype`, `backend`, `flops_per_sec`) — keep field names stable; report/ingest/CI all parse them.
