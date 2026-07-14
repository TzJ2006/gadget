"""
CPU benchmarking - single-core and all-cores FLOPS measurement.
"""
import math
import multiprocessing
import numpy as np
from typing import Dict, Any

try:
    from threadpoolctl import threadpool_limits
    HAS_THREADPOOLCTL = True
except ImportError:
    HAS_THREADPOOLCTL = False

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

from .core import BaseBenchmark, calculate_flops_scalar, calculate_flops_gemm


# Scalar loop for single-core benchmark
def _cpu_loop(n: int) -> float:
    """Pure Python CPU loop (sqrt + add)."""
    s = 0.0
    for i in range(n):
        s += math.sqrt(i)
    return s


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


class CpuAllCoresBenchmark(BaseBenchmark):
    """
    All-cores CPU benchmark using NumPy BLAS GEMM.

    This leverages optimized BLAS libraries (OpenBLAS, MKL, Accelerate)
    for multi-threaded matrix multiplication.
    """

    # Default matrix size for GEMM
    MATRIX_SIZE = 4096

    def __init__(self, matrix_size: int = None, num_threads: int = None,
                 warmup_iters: int = 3, measure_iters: int = 5):
        super().__init__(warmup_iters, measure_iters)
        self.matrix_size = matrix_size or self.MATRIX_SIZE
        self.num_threads = num_threads or multiprocessing.cpu_count()
        # Pre-generate matrices to exclude generation time from measurement
        self.A = np.random.random((self.matrix_size, self.matrix_size)).astype(np.float32)
        self.B = np.random.random((self.matrix_size, self.matrix_size)).astype(np.float32)

    def get_info(self) -> Dict[str, Any]:
        return {
            'name': f'CPU All-Cores ({self.num_threads} threads)',
            'type': 'cpu_all_cores',
            'backend': 'cpu',
            'dtype': 'float32',
            'matrix_size': self.matrix_size,
            'iterations': self.timer.measure_iters,
        }

    def run_iteration(self) -> None:
        # Limit BLAS threads if threadpoolctl is available
        if HAS_THREADPOOLCTL:
            with threadpool_limits(limits=self.num_threads):
                np.dot(self.A, self.B)
        else:
            np.dot(self.A, self.B)

    def get_flops(self, iterations: int) -> int:
        return calculate_flops_gemm(self.matrix_size, iterations)


class CpuSingleCoreBLASBenchmark(BaseBenchmark):
    """
    Single-core CPU benchmark using NumPy BLAS with thread limit.

    This measures single-core BLAS performance by limiting NumPy to 1 thread.
    """

    MATRIX_SIZE = 2048

    def __init__(self, matrix_size: int = None, warmup_iters: int = 3,
                 measure_iters: int = 5):
        super().__init__(warmup_iters, measure_iters)
        self.matrix_size = matrix_size or self.MATRIX_SIZE
        # Pre-generate matrices to exclude generation time from measurement
        self.A = np.random.random((self.matrix_size, self.matrix_size)).astype(np.float32)
        self.B = np.random.random((self.matrix_size, self.matrix_size)).astype(np.float32)

    def get_info(self) -> Dict[str, Any]:
        return {
            'name': 'CPU Single-Core BLAS',
            'type': 'cpu_single_core_blas',
            'backend': 'cpu',
            'dtype': 'float32',
            'matrix_size': self.matrix_size,
            'iterations': self.timer.measure_iters,
        }

    def run_iteration(self) -> None:
        # Limit to 1 BLAS thread
        if HAS_THREADPOOLCTL:
            with threadpool_limits(limits=1):
                np.dot(self.A, self.B)
        else:
            np.dot(self.A, self.B)

    def get_flops(self, iterations: int) -> int:
        return calculate_flops_gemm(self.matrix_size, iterations)


def run_all_cpu_benchmarks(duration: float = None, show_progress: bool = True) -> list:
    """
    Run all CPU benchmarks and return results.

    Args:
        duration: Target duration per benchmark in seconds
        show_progress: Whether to show progress bars

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

        if show_progress and HAS_TQDM and duration:
            # Show progress bar for duration-based benchmarks
            print(f"  [{i}/3] {name}...")
            result = bench.benchmark()
            results.append(result)
            print(f"       Result: {result['flops_formatted']}")
        else:
            print(f"  [{i}/3] {name}...")
            result = bench.benchmark()
            results.append(result)
            print(f"       Result: {result['flops_formatted']}")

    print("✓ CPU benchmarks complete.\n")

    return results
