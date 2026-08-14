"""
CPU benchmarking - single-core and all-cores FLOPS measurement.
"""
import math
import multiprocessing
import os
from contextlib import contextmanager, nullcontext
from typing import Dict, Any

import numpy as np

try:
    from threadpoolctl import threadpool_limits
    HAS_THREADPOOLCTL = True
except ImportError:
    HAS_THREADPOOLCTL = False

from .core import BaseBenchmark, calculate_flops_scalar, calculate_flops_gemm


_BLAS_THREAD_WARNED = False


# Scalar loop for single-core benchmark
def _cpu_loop(n: int) -> float:
    """Pure Python CPU loop (sqrt + add)."""
    s = 0.0
    for i in range(n):
        s += math.sqrt(i)
    return s


@contextmanager
def _env_thread_limit(n: int):
    """Best-effort BLAS thread cap via env vars when threadpoolctl is missing."""
    keys = ('OMP_NUM_THREADS', 'MKL_NUM_THREADS')
    saved = {k: os.environ.get(k) for k in keys}
    for k in keys:
        os.environ[k] = str(n)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def _blas_limits(num_threads: int):
    """Limit BLAS threads for one GEMM; warn once if falling back to env vars."""
    global _BLAS_THREAD_WARNED
    if HAS_THREADPOOLCTL:
        return threadpool_limits(limits=num_threads)
    if num_threads == 1:
        if not _BLAS_THREAD_WARNED:
            print("Warning: threadpoolctl is not installed; "
                  "setting OMP_NUM_THREADS/MKL_NUM_THREADS=1 for single-core BLAS. "
                  "Install threadpoolctl for precise BLAS thread control.")
            _BLAS_THREAD_WARNED = True
        return _env_thread_limit(1)
    return nullcontext()


class CpuSingleCoreBenchmark(BaseBenchmark):
    """
    Single-core CPU benchmark using pure Python operations.

    This measures CPU performance without leveraging BLAS or vectorization.
    """

    # Number of operations per iteration (reduced for faster testing)
    ITERATIONS = 10_000_000

    def __init__(self, warmup_iters: int = 5, measure_iters: int = 5):
        # Reduce iterations for single-core since it's slower
        super().__init__(warmup_iters, measure_iters)
        self.iterations = self.ITERATIONS

    def get_info(self) -> Dict[str, Any]:
        return {
            'name': 'CPU Single-Core',
            'type': 'cpu_single_core',
            'backend': 'cpu',
            'dtype': 'N/A',
            'iterations': self.iterations,
        }

    def run_iteration(self) -> None:
        _cpu_loop(self.iterations)

    def get_flops(self, iterations: int) -> int:
        return calculate_flops_scalar(self.iterations * iterations)


class _CpuBlasBenchmark(BaseBenchmark):
    """NumPy BLAS GEMM with a configurable thread limit."""

    def __init__(self, matrix_size: int, num_threads: int,
                 name: str, type_key: str,
                 warmup_iters: int = 3, measure_iters: int = 5):
        super().__init__(warmup_iters, measure_iters)
        self.matrix_size = matrix_size
        self.num_threads = num_threads
        self._name = name
        self._type_key = type_key
        # Pre-generate matrices to exclude generation time from measurement
        self.A = np.random.random((self.matrix_size, self.matrix_size)).astype(np.float32)
        self.B = np.random.random((self.matrix_size, self.matrix_size)).astype(np.float32)

    def get_info(self) -> Dict[str, Any]:
        return {
            'name': self._name,
            'type': self._type_key,
            'backend': 'cpu',
            'dtype': 'float32',
            'matrix_size': self.matrix_size,
            'iterations': self.timer.measure_iters,
        }

    def run_iteration(self) -> None:
        with _blas_limits(self.num_threads):
            np.dot(self.A, self.B)

    def get_flops(self, iterations: int) -> int:
        return calculate_flops_gemm(self.matrix_size, iterations)


class CpuAllCoresBenchmark(_CpuBlasBenchmark):
    """
    All-cores CPU benchmark using NumPy BLAS GEMM.

    This leverages optimized BLAS libraries (OpenBLAS, MKL, Accelerate)
    for multi-threaded matrix multiplication.
    """

    MATRIX_SIZE = 4096

    def __init__(self, matrix_size: int = None, num_threads: int = None,
                 warmup_iters: int = 3, measure_iters: int = 5):
        threads = num_threads or multiprocessing.cpu_count()
        super().__init__(
            matrix_size=matrix_size or self.MATRIX_SIZE,
            num_threads=threads,
            name=f'CPU All-Cores ({threads} threads)',
            type_key='cpu_all_cores',
            warmup_iters=warmup_iters,
            measure_iters=measure_iters,
        )


class CpuSingleCoreBLASBenchmark(_CpuBlasBenchmark):
    """
    Single-core CPU benchmark using NumPy BLAS with thread limit.

    This measures single-core BLAS performance by limiting NumPy to 1 thread.
    """

    MATRIX_SIZE = 2048

    def __init__(self, matrix_size: int = None, warmup_iters: int = 3,
                 measure_iters: int = 5):
        super().__init__(
            matrix_size=matrix_size or self.MATRIX_SIZE,
            num_threads=1,
            name='CPU Single-Core BLAS',
            type_key='cpu_single_core_blas',
            warmup_iters=warmup_iters,
            measure_iters=measure_iters,
        )


def run_all_cpu_benchmarks(duration: float = None, show_progress: bool = True) -> list:
    """
    Run all CPU benchmarks and return results.

    Args:
        duration: Target duration per benchmark in seconds
        show_progress: Unused; kept for compatibility.

    Returns:
        List of benchmark result dictionaries.
    """
    results = []

    print("Running CPU benchmarks...")

    benchmarks = [
        ("Single-core (scalar operations)", CpuSingleCoreBenchmark()),
        ("Single-core BLAS (matrix multiplication)", CpuSingleCoreBLASBenchmark()),
        ("All-cores BLAS (matrix multiplication)", CpuAllCoresBenchmark()),
    ]

    for i, (name, bench) in enumerate(benchmarks, 1):
        if duration:
            bench.timer.target_duration = duration

        print(f"  [{i}/3] {name}...")
        result = bench.benchmark()
        results.append(result)
        print(f"       Result: {result['flops_formatted']}")

    print("✓ CPU benchmarks complete.\n")

    return results
