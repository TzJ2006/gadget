"""
Cross-platform CPU/GPU Benchmarking Tool

A unified benchmarking solution supporting:
- Platforms: macOS, Linux, Windows
- CPU: Single-core and all-core FLOPS
- GPU: NVIDIA (CUDA), Apple (MPS), Intel, AMD - all precision levels
"""

# Fix OpenMP library conflict on Windows (NumPy + PyTorch both link OpenMP)
import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

from .core import BaseBenchmark, fmt_flops, calculate_flops_gemm, RobustTimer, BenchmarkResults
from .detect import get_cpu_info, get_gpu_info, get_system_info
from .cpu import CpuSingleCoreBenchmark, CpuAllCoresBenchmark
from .gpu import GpuBenchmark

# report/publish pull plotly — load only when asked (so --info works without it)
_LAZY_ATTRS = {
    'BenchmarkReport': ('.report', 'BenchmarkReport'),
    'generate_report': ('.report', 'generate_report'),
    'stage_benchmark_report': ('.publish', 'stage_benchmark_report'),
}

__all__ = [
    # Core
    'BaseBenchmark',
    'fmt_flops',
    'calculate_flops_gemm',
    'RobustTimer',
    'BenchmarkResults',
    # Detection
    'get_cpu_info',
    'get_gpu_info',
    'get_system_info',
    # CPU
    'CpuSingleCoreBenchmark',
    'CpuAllCoresBenchmark',
    # GPU
    'GpuBenchmark',
    # Report (lazy)
    'BenchmarkReport',
    'generate_report',
    'stage_benchmark_report',
]


def __getattr__(name):
    target = _LAZY_ATTRS.get(name)
    if target is None:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    module_name, attr = target
    from importlib import import_module
    value = getattr(import_module(module_name, __package__), attr)
    globals()[name] = value
    return value


__version__ = '1.1.0'
