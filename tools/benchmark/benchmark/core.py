"""
Core benchmarking infrastructure - base classes and utilities.
"""
import os
import csv
import time
import math
import numpy as np
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable
from pathlib import Path


def fmt_flops(flops: float) -> str:
    """Format FLOPS value to appropriate unit."""
    for unit, threshold in [('PFLOPS', 1e15), ('TFLOPS', 1e12),
                            ('GFLOPS', 1e9), ('MFLOPS', 1e6), ('KFLOPS', 1e3)]:
        if flops >= threshold:
            return f"{flops/threshold:,.2f} {unit}/s"
    return f"{flops:,.2f} FLOPS/s"


def calculate_flops_gemm(n: int, iterations: int = 1) -> int:
    """Calculate FLOPS for GEMM: 2 * N^3 * iterations."""
    return 2 * (n ** 3) * iterations


def calculate_flops_scalar(iterations: int) -> int:
    """Calculate FLOPS for scalar operations: 2 * iterations (sqrt + add)."""
    return 2 * iterations


class RobustTimer:
    """
    Robust timer with warmup and outlier removal using IQR method.
    Supports both fixed iterations and duration-based measurement.
    """

    def __init__(self, warmup_iters: int = 100, measure_iters: int = 50,
                 target_duration: float = None):
        """
        Initialize timer.

        Args:
            warmup_iters: Number of warmup iterations
            measure_iters: Number of measurement iterations (used if target_duration is None)
            target_duration: Target duration in seconds (overrides measure_iters)
        """
        self.warmup_iters = warmup_iters
        self.measure_iters = measure_iters
        self.target_duration = target_duration

    def time(self, func: Callable[[], float]) -> Dict[str, float]:
        """
        Time a function and return statistics.

        Args:
            func: A callable that performs the operation and returns duration in seconds.

        Returns:
            Dictionary with mean, median, std, min, max statistics.
        """
        # Warmup phase
        for _ in range(self.warmup_iters):
            func()

        # If target_duration is specified, estimate iterations first
        if self.target_duration is not None:
            # Quick calibration run
            calib_times = []
            for _ in range(5):
                calib_times.append(func())
            avg_time = np.mean(calib_times)

            # Calculate iterations needed for target duration
            self.measure_iters = max(1, int(self.target_duration / avg_time))

        # Measurement phase
        times = []
        for _ in range(self.measure_iters):
            times.append(func())

        # Convert to numpy array for statistical analysis
        times_array = np.array(times)

        # Remove outliers using IQR method
        q1, q3 = np.percentile(times_array, [25, 75])
        iqr = q3 - q1
        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr

        filtered_times = times_array[
            (times_array >= lower_bound) & (times_array <= upper_bound)
        ]

        return {
            'mean': float(np.mean(filtered_times)),
            'median': float(np.median(filtered_times)),
            'std': float(np.std(filtered_times)),
            'min': float(np.min(filtered_times)),
            'max': float(np.max(filtered_times)),
            'outliers_removed': len(times) - len(filtered_times),
            'actual_iters': len(filtered_times),
            'actual_duration': float(np.sum(filtered_times)),
        }


class BaseBenchmark(ABC):
    """
    Abstract base class for all benchmarks.
    """

    def __init__(self, warmup_iters: int = 100, measure_iters: int = 50):
        self.timer = RobustTimer(warmup_iters, measure_iters)

    @abstractmethod
    def get_info(self) -> Dict[str, Any]:
        """Return benchmark information (name, description, etc.)."""
        pass

    @abstractmethod
    def run_iteration(self) -> None:
        """Run a single benchmark iteration."""
        pass

    @abstractmethod
    def get_flops(self, iterations: int) -> int:
        """Calculate total FLOPS for given iterations."""
        pass

    def benchmark(self) -> Dict[str, Any]:
        """
        Run benchmark and return results.

        Returns:
            Dictionary with benchmark info, statistics, and FLOPS.
        """
        def timed_run():
            start = time.perf_counter()
            self.run_iteration()
            return time.perf_counter() - start

        stats = self.timer.time(timed_run)
        info = self.get_info()

        # Calculate FLOPS based on median time
        # FLOPS per single iteration (fixed value, independent of measurement iterations)
        flops_per_iteration = self.get_flops(1)
        median_time = stats['median']
        flops_per_sec = flops_per_iteration / median_time if median_time > 0 else 0

        result = {
            **info,
            'stats': stats,
            'flops_per_sec': flops_per_sec,
            'flops_formatted': fmt_flops(flops_per_sec),
        }

        return result


class BenchmarkResults:
    """
    Manage and save benchmark results to CSV.
    """

    def __init__(self, output_path: str = ''):
        if not output_path:
            from common.paths import TOOLS_DIR
            output_path = str(TOOLS_DIR / "benchmark" / "benchmark_results.csv")
        self.output_path = Path(output_path)
        self.results: List[Dict[str, Any]] = []

    def add(self, result: Dict[str, Any], system_info: Dict[str, Any]):
        """
        Add a benchmark result with system information.

        Args:
            result: Benchmark result from BaseBenchmark.benchmark()
            system_info: System information from get_system_info()
        """
        timestamp = datetime.now().isoformat()

        # Flatten system info
        cpu_info = system_info.get('cpu', {})
        gpus_info = system_info.get('gpus', [])
        software_info = system_info.get('software', {})

        # Extract first GPU info if available
        gpu_info = gpus_info[0] if gpus_info else {}

        row = {
            'timestamp': timestamp,
            # CPU info
            'cpu_model': cpu_info.get('model', 'Unknown'),
            'cpu_cores': cpu_info.get('cores', 0),
            'cpu_frequency': cpu_info.get('frequency', 'Unknown'),
            # GPU info
            'gpu_vendor': gpu_info.get('vendor', 'N/A'),
            'gpu_model': gpu_info.get('model', 'N/A'),
            'gpu_memory_gb': gpu_info.get('memory_gb', 0),
            'gpu_compute_capability': gpu_info.get('compute_capability', 'N/A'),
            # Benchmark specific
            'benchmark_name': result.get('name', 'Unknown'),
            'benchmark_type': result.get('type', 'Unknown'),
            'backend': result.get('backend', 'cpu'),
            'dtype': result.get('dtype', 'N/A'),
            'matrix_size': result.get('matrix_size', 0),
            # Results
            'flops_gflops': round(result.get('flops_per_sec', 0) / 1e9, 2),
            'time_seconds': round(result.get('stats', {}).get('median', 0), 6),
            'iterations': result.get('iterations', 0),
            # Software info
            'os': software_info.get('os', 'Unknown'),
            'python_version': software_info.get('python', 'Unknown'),
            'torch_version': software_info.get('torch', 'N/A'),
            'cuda_version': software_info.get('cuda', 'N/A'),
        }

        self.results.append(row)

    def save(self):
        """Save results to CSV file (append mode)."""
        if not self.results:
            return

        file_exists = self.output_path.exists()
        # Append mode does not create missing parent dirs — ensure they exist
        # or the first run on a fresh checkout loses the whole benchmark run.
        self.output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(self.output_path, 'a', newline='', encoding='utf-8') as f:
            fieldnames = list(self.results[0].keys())
            writer = csv.DictWriter(f, fieldnames=fieldnames)

            # Write header only if file is new
            if not file_exists:
                writer.writeheader()

            for row in self.results:
                writer.writerow(row)

        print(f"Results saved to: {self.output_path.absolute()}")
        # File now holds all rows (existing + just-written); count once.
        print(f"Total records in file: {self._count_existing_rows()}")

        # Clear results after saving
        self.results.clear()

    def _count_existing_rows(self) -> int:
        """Count existing rows in CSV (excluding header)."""
        try:
            with open(self.output_path, 'r', encoding='utf-8') as f:
                return sum(1 for _ in f) - 1  # Exclude header
        except (OSError, UnicodeError):
            return 0
