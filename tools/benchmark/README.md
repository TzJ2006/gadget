# Cross-Platform CPU/GPU Benchmarking Tool

A unified benchmarking solution for measuring CPU and GPU FLOPS performance across different hardware platforms.

## Features

- **Cross-platform**: macOS, Linux, Windows
- **CPU Benchmarks**: Single-core and all-cores FLOPS measurement
- **GPU Support**: NVIDIA (CUDA), Apple Silicon (MPS), Intel (XPU). (`detect.py` may list OpenCL devices for `--info`; `gpu.py` does **not** run OpenCL benchmarks.)
- **Multiple Precisions**: FP64, FP32, FP16, BF16 (bfloat16), FP8 (experimental)
- **Duration Control**: Configurable per-test duration (default 10 seconds, `--duration`)
- **Accurate Measurement**: Warmup runs, statistical analysis (median, IQR outlier removal)
- **HTML Reports**: Interactive leaderboards and charts with historical data tracking

## Quick Start

### Installation

```bash
# Install from requirements.txt
pip install -r requirements.txt

# Or install manually
pip install torch numpy pandas plotly tqdm

# Optional dependencies
pip install threadpoolctl  # For precise BLAS thread control
# pyopencl: optional for OpenCL *detection* in --info only (not used by gpu benchmarks)
```

### Usage

```bash
# Run all benchmarks (results append to CSV)
python -m benchmark.cli

# CPU benchmarks only
python -m benchmark.cli --cpu-only

# GPU benchmarks only
python -m benchmark.cli --gpu-only

# Generate HTML report
python -m benchmark.cli --report-only

# Run benchmarks + auto-generate report
python -m benchmark.cli --report

# Control benchmark duration (default 10 seconds, use 60 for 1 minute)
python -m benchmark.cli --duration 60
```

### Output

- **CSV SoT (single file)**: `tools/benchmark/benchmark_results.csv` — CLI default, submit/ingest, and CI (append mode)
- **HTML report**: `outputs/reports/benchmark/report.html` - Interactive leaderboards and charts

Output paths are relative to the project root (`gadget/`). Override with `--output` (CSV) and `--report-output` (HTML).

## Website Auto-Update Pipeline

This repo includes a GitHub-based pipeline to publish `benchmark_report.html` as a website and keep it updated from queued submissions.

### Workflow Files

- `.github/workflows/accept-submission.yml`
  - Receives `repository_dispatch` event `benchmark_submission`
  - Appends payload to `data/pending_submissions.ndjson`
- `.github/workflows/daily-publish.yml`
  - Runs daily (`00:00 UTC`) or manually
  - Ingests queue with strict validation/dedupe/sanitization
  - Regenerates `benchmark_report.html` when dataset changes
- `.github/workflows/pages-deploy.yml`
  - Deploys `benchmark_report.html` to GitHub Pages

### Submission Helpers

```bash
# Dry-run preview from latest CSV row
python scripts/submit_result.py --dry-run

# Submit latest row to a relay endpoint
python scripts/submit_result.py --relay-url https://your-relay.example.com/submit

# Trusted direct GitHub dispatch (token required)
python scripts/submit_result.py \
  --github-owner YOUR_ORG \
  --github-repo YOUR_REPO \
  --github-token "$GITHUB_TOKEN"
```

### Upload Prompt in Benchmark CLI

After a benchmark run that saves results, `benchmark.cli` can ask whether to upload the latest row to the public leaderboard.

```bash
# Use relay URL directly (interactive prompt appears after run, default is No)
python -m benchmark.cli --relay-url https://your-relay.example.com/submit

# Use environment fallback for relay URL
export BENCHMARK_RELAY_URL=https://your-relay.example.com/submit
python -m benchmark.cli

# Non-interactive upload
python -m benchmark.cli --upload --relay-url https://your-relay.example.com/submit

# Explicitly disable upload flow
python -m benchmark.cli --no-upload
```

Notes:
- Prompt appears only for benchmark runs with saving enabled (`--no-save` disables it).
- Upload failures do not fail local benchmarking.
- `--report-only` and `--info` do not trigger upload behavior.

### Ingestion (Local Test)

```bash
python scripts/ingest_submissions.py \
  --pending-file data/pending_submissions.ndjson \
  --csv-path benchmark_results.csv \
  --rejected-file data/rejected_submissions.ndjson \
  --log-file data/ingest_log.json
```

Queue/audit files:
- `data/pending_submissions.ndjson`: raw queued submissions
- `data/rejected_submissions.ndjson`: rejected records with reasons
- `data/ingest_log.json`: latest ingest summary

### GitHub Setup Checklist

- Enable **GitHub Pages** with source set to **GitHub Actions**.
- Ensure workflow permissions allow repository write access for Actions.
- If using direct dispatch, use a token that can call repository dispatch events.
- For public intake, run a separate relay service that validates/rate-limits requests and forwards payloads to `repository_dispatch`.

## Benchmark Types

### CPU Benchmarks

| Benchmark | Description |
|-----------|-------------|
| Single-Core (Scalar) | Pure Python operations (sqrt + add) |
| Single-Core BLAS | NumPy matrix multiplication (1 thread) |
| All-Cores BLAS | NumPy matrix multiplication (all CPU cores) |

### GPU Benchmarks

| Precision | Description |
|-----------|-------------|
| FP64 | Double precision (64-bit) |
| FP32 | Single precision (32-bit) |
| FP16 | Half precision (16-bit) |
| BF16 | Brain Float 16 (better dynamic range) |
| FP8_exp | 8-bit float (experimental, limited support) |

## Historical Test Results

### GPU Speed Tests

### NVIDIA RTX 2060:
![2060](results/GPU%20speed%20test/2060.jpg)

### NVIDIA RTX 2080 Ti:
![2080Ti](results/GPU%20speed%20test/2080Ti.jpg)

### NVIDIA A100:
![A100](results/GPU%20speed%20test/A100.jpg)

### NVIDIA RTX 5000 Ada:
![RTX5000ada](results/GPU%20speed%20test/RTX5000ada.jpg)

### NVIDIA RTX 6000 Ada:
![RTX6000ada](results/GPU%20speed%20test/RTX6000ada.jpg)

### Apple M4 Pro:
![M4 pro](results/GPU%20speed%20test/M4%20pro.png)

## Module Structure

```
benchmark/                     # Project root (renamed from test/)
├── benchmark/
│   ├── __init__.py    # Module exports
│   ├── cli.py         # Command-line interface
│   ├── core.py        # Base classes and utilities (RobustTimer, CSV handling)
│   ├── cpu.py         # CPU benchmarks (single-core scalar, BLAS)
│   ├── detect.py      # Hardware detection (CPU, GPU, system info)
│   ├── gpu.py         # GPU benchmarks (CUDA, MPS, XPU)
│   ├── report.py      # HTML report generation (Plotly charts, leaderboards)
│   └── README.md      # Detailed module documentation
├── scripts/           # Submission helpers (submit_result.py, ingest_submissions.py)
├── data/              # Queue/audit files (pending/rejected submissions)
├── results/           # Historical GPU test screenshots
├── .github/workflows/ # CI/CD (accept-submission, daily-publish, pages-deploy)
├── README.md          # This file
├── CLAUDE.md          # Dev guide
└── requirements.txt   # Dependencies
```

## Advanced Usage

```bash
# Custom CSV output
python -m benchmark.cli --output my_results.csv

# Custom matrix size
python -m benchmark.cli --matrix-size 8192

# Control benchmark duration per test (in seconds)
python -m benchmark.cli --duration 60  # 1 minute per benchmark
python -m benchmark.cli --duration 300  # 5 minutes per benchmark

# Run without saving to CSV
python -m benchmark.cli --no-save

# Generate report from specific CSV
python -m benchmark.cli --report-only --input-csv my_results.csv --report-output report.html

# Show system information
python -m benchmark.cli --info

# Quiet mode (minimal output)
python -m benchmark.cli --quiet

# Verbose mode (detailed output)
python -m benchmark.cli --verbose
```

## CSV Format

The CSV file contains all benchmark results with the following columns:

| Column | Description |
|--------|-------------|
| `timestamp` | ISO format timestamp |
| `cpu_model` | CPU model name |
| `cpu_cores` | Number of CPU cores |
| `gpu_model` | GPU model name |
| `backend` | cuda/mps/xpu |
| `dtype` | FP64/FP32/FP16/BF16 |
| `flops_gflops` | Performance in GFLOPS |
| `os` | Operating system |
| `python_version` | Python version |
| `torch_version` | PyTorch version |
| `cuda_version` | CUDA version (if applicable) |

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
