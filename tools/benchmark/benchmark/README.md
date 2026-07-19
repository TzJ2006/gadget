# Cross-Platform CPU/GPU Benchmarking Tool

A unified, cross-platform benchmarking solution for measuring CPU and GPU FLOPS performance across different hardware vendors and precision levels.

## Features

- **Cross-platform**: Supports macOS, Linux, Windows
- **CPU Benchmarks**: Single-core and all-cores FLOPS measurement
- **GPU Support**: NVIDIA (CUDA), Apple Silicon (MPS), Intel (XPU). OpenCL may appear in `--info` detection only; not benchmarked.
- **All Precision Levels**: FP64, FP32, FP16, BF16, FP8 (where supported)
- **Accurate Measurement**: Warmup runs, statistical analysis (median, IQR outlier removal)
- **CSV Output**: Append results to CSV with full hardware/software information

## Installation

```bash
# Install from requirements.txt (recommended)
pip install -r requirements.txt

# Or install manually
pip install torch numpy pandas plotly tqdm

# Optional dependencies
pip install threadpoolctl  # For precise BLAS thread control
# pyopencl: optional for OpenCL detection in --info only (not used by gpu.py)
```

## Usage

### Basic Usage

```bash
# Run all benchmarks (CPU + GPU)
python -m benchmark.cli

# CPU benchmarks only
python -m benchmark.cli --cpu-only

# GPU benchmarks only
python -m benchmark.cli --gpu-only

# Custom output file
python -m benchmark.cli --output my_results.csv

# Generate HTML report from existing CSV
python -m benchmark.cli --report-only

# Run benchmarks + auto-generate report
python -m benchmark.cli --report

# Control benchmark duration per test (default 10 seconds)
python -m benchmark.cli --duration 60

# Run without saving to CSV
python -m benchmark.cli --no-save

# Quiet mode (minimal output)
python -m benchmark.cli --quiet

# Show system information only
python -m benchmark.cli --info
```

### Default Output Paths

- **CSV**: `outputs/data/benchmark/results.csv` (relative to project root)
- **HTML report**: `outputs/reports/benchmark/report.html` (relative to project root)

Override with `--output` (CSV) and `--report-output` (HTML).

### Python API

```python
from benchmark import get_system_info, cpu, gpu, core

# Get system information
system_info = get_system_info()

# Run CPU benchmarks
cpu_results = cpu.run_all_cpu_benchmarks()

# Run GPU benchmarks
gpu_results = gpu.run_all_gpu_benchmarks()

# Save to CSV
results_manager = core.BenchmarkResults('output.csv')
for result in cpu_results + gpu_results:
    results_manager.add(result, system_info)
results_manager.save()
```

## Benchmark Types

### CPU Benchmarks

1. **Single-Core (Scalar)**: Pure Python operations (sqrt + add)
2. **Single-Core BLAS**: NumPy matrix multiplication with 1 thread
3. **All-Cores BLAS**: NumPy matrix multiplication with all CPU cores

### GPU Benchmarks

| Precision | Description | Notes |
|-----------|-------------|-------|
| FP64 | Double precision (64-bit) | MPS doesn't support FP64 |
| FP32 | Single precision (32-bit) | Universal |
| FP16 | Half precision (16-bit) | Universal |
| BF16 | Brain Float 16 | CUDA 8.0+, XPU; MPS unsupported |
| FP8_exp | 8-bit float (experimental) | CUDA 8.9+ only |

## CSV Output Format

The CSV file uses **append mode** — it never overwrites existing data. This enables accumulation across different hardware and historical tracking. The file contains the following columns:

| Column | Description |
|--------|-------------|
| `timestamp` | ISO format timestamp |
| `cpu_model` | CPU model name |
| `cpu_cores` | Number of CPU cores |
| `cpu_frequency` | CPU frequency in GHz |
| `gpu_vendor` | GPU vendor (NVIDIA/Apple/Intel/AMD) |
| `gpu_model` | GPU model name |
| `gpu_memory_gb` | GPU memory in GB |
| `gpu_compute_capability` | Compute capability version |
| `benchmark_name` | Benchmark name |
| `benchmark_type` | Type (cpu_single_core, cpu_all_cores, gpu) |
| `backend` | Backend (cpu/cuda/mps/xpu) |
| `dtype` | Data type (FP64/FP32/FP16/BF16/FP8) |
| `matrix_size` | Matrix size for GEMM benchmarks |
| `flops_gflops` | Performance in GFLOPS |
| `time_seconds` | Median time per iteration |
| `iterations` | Number of iterations |
| `os` | Operating system |
| `python_version` | Python version |
| `torch_version` | PyTorch version |
| `cuda_version` | CUDA version (if applicable) |

## Examples

### Example Output

```
============================================================
Cross-Platform CPU/GPU Benchmarking Tool
============================================================

============================================================
System Information
============================================================

CPU: AMD EPYC 7513 32-Core Processor
  Cores: 128
  Frequency: 2.0 GHz
  Architecture: x86_64

GPU(s): 1 detected
  [0] NVIDIA RTX 4090
      Memory: 24 GB
      Backend: cuda
      Compute: 8.9

Software:
  OS: Linux 5.15.0-119-generic
  Python: 3.10.16
  PyTorch: 2.10.0+cu130
  CUDA: 13.0
============================================================

Running CPU benchmarks...
  [1/3] Single-core (scalar operations)...
       Result: 120.83 GFLOPS/s
  [2/3] Single-core BLAS (matrix multiplication)...
       Result: 291.18 GFLOPS/s
  [3/3] All-cores BLAS (matrix multiplication)...
       Result: 491.80 GFLOPS/s
✓ CPU benchmarks complete.

Running GPU benchmarks...
  Detected 1 device(s) with 1 backend(s)

  [NVIDIA GeForce RTX 4090]
    [1/5] FP64... ✓ 1.18 TFLOPS/s
    [2/5] FP32... ✓ 52.84 TFLOPS/s
    [3/5] FP16... ✓ 141.04 TFLOPS/s
    [4/5] BF16... ✓ 143.20 TFLOPS/s
    [5/5] FP8_exp... ✗ (not supported)
✓ GPU benchmarks complete.

Results saved to: outputs/data/benchmark/results.csv
Total records in file: 8
```

## Module Structure

```
benchmark/
├── __init__.py    # Module exports (BenchmarkReport, generate_report, etc.)
├── cli.py         # Command-line interface with argparse
├── core.py        # BaseBenchmark, RobustTimer, BenchmarkResults, CSV handling
├── cpu.py         # CpuSingleCoreBenchmark, CpuAllCoresBenchmark
├── detect.py      # get_cpu_info(), get_gpu_info(), get_system_info()
├── gpu.py         # GpuBenchmark (CUDA, MPS, XPU)
├── report.py      # BenchmarkReport (HTML generation with Plotly charts)
└── README.md      # This file
```

## Technical Details

### FLOPS Calculation

- **CPU Scalar**: `2 * iterations` (sqrt + add per iteration)
- **GEMM**: `2 * N³ * iterations` (multiply-add operations)

### Measurement Methodology

1. **Warmup Phase**: 5-100 iterations (depending on benchmark type)
2. **Measurement Phase**: 5-50 iterations
3. **Statistical Analysis**: Median time with IQR-based outlier removal
4. **GPU Synchronization**: Explicit synchronization for accurate timing

### Platform Support

| Platform | CPU | GPU (NVIDIA) | GPU (Apple) | GPU (Intel) | GPU (AMD) |
|----------|-----|--------------|-------------|-------------|-----------|
| Linux    | ✓   | ✓ (CUDA)     | ✗           | ✓ (XPU/OCL) | ✓ (OCL)   |
| macOS    | ✓   | ✗            | ✓ (MPS)     | ✗           | ✗         |
| Windows  | ✓   | ✓ (CUDA)     | ✗           | ✓ (XPU/OCL) | ✓ (OCL)   |

### dtype Support by Backend

| dtype   | CUDA | MPS  | XPU  | Notes                    |
|---------|------|------|------|--------------------------|
| FP64    | ✓    | ✗    | ✓    | MPS doesn't support FP64 |
| FP32    | ✓    | ✓    | ✓    | Universal                |
| FP16    | ✓    | ✓    | ✓    | Universal                |
| BF16    | ✓    | ✗    | ✓    | CUDA 8.0+, XPU           |
| FP8_exp | ✓*   | ✗    | ✗    | CUDA 8.9+, experimental  |

## Notes

- GPU support depends on PyTorch installation with appropriate backends
- FP8 support requires CUDA compute capability 8.9+ and compatible PyTorch build
- For best accuracy, close other applications while benchmarking
- Results may vary between runs due to thermal throttling and background processes

## License

This benchmark tool is part of the test repository and follows the same license.
