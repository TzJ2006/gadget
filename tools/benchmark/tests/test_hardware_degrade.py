"""Hardware detection and VRAM sizing degrade instead of crashing.

Almost everything correct about this code is a degradation path, and degradation
paths are exactly what never fires on the author's machine — which has a GPU and
a full deep-learning stack. Someone running this on a GPU-less server is the one
who hits them, and the author never sees it.

Pure-mock: torch is not installed here, which makes the no-torch path the
default rather than something to simulate.
"""

import math
from unittest.mock import patch

from benchmark.detect import get_cpu_info, get_gpu_info, get_system_info
from benchmark.gpu import calculate_matrix_size_from_memory


# ─── detection without a deep-learning stack ─────────────────────────

def test_gpu_detection_without_torch_returns_empty_not_an_error():
    """--info must still answer "what hardware is here" with no torch."""
    assert get_gpu_info() == []


def test_gpu_detection_survives_a_torch_that_raises():
    """A broken/partial install must not take the whole probe down."""
    class Exploding:
        def __getattr__(self, name):
            raise RuntimeError("CUDA driver version is insufficient")

    with patch.dict("sys.modules", {"torch": Exploding()}):
        try:
            gpus = get_gpu_info()
        except RuntimeError:
            raise AssertionError("a broken torch must not propagate out of detection")
    assert isinstance(gpus, list)


def test_cpu_info_always_answers():
    info = get_cpu_info()
    for key in ("model", "cores", "architecture", "frequency"):
        assert key in info, f"missing {key}"
    assert isinstance(info["cores"], int)


def test_system_info_is_complete_without_a_gpu():
    info = get_system_info()
    assert set(info) >= {"cpu", "gpus", "software"}
    assert info["gpus"] == []
    assert info["software"].get("python")


# ─── matrix size from VRAM ───────────────────────────────────────────

def test_more_vram_never_gives_a_smaller_matrix():
    sizes = [calculate_matrix_size_from_memory(gb) for gb in (1, 2, 4, 8, 16, 24, 48, 80)]
    assert sizes == sorted(sizes), f"not monotonic: {sizes}"


def test_every_size_is_a_usable_power_of_two():
    for gb in (0, 0.001, 0.5, 1, 8, 24, 80, 1024):
        n = calculate_matrix_size_from_memory(gb)
        assert n >= 256, f"{gb}GB produced an unusably small {n}"
        assert n == 2 ** round(math.log2(n)), f"{n} is not a power of two"


def test_unknown_memory_falls_back_to_a_default():
    assert calculate_matrix_size_from_memory(0) == 2048
    assert calculate_matrix_size_from_memory(-5) == 2048


def test_a_tiny_card_still_gets_a_legal_size():
    """The floor matters more than the ceiling: 256 must never become 0 or 1."""
    assert calculate_matrix_size_from_memory(0.001) == 256


def test_the_chosen_matrix_fits_in_the_budget_it_claims():
    """Three FP32 matrices must fit in the tenth of VRAM the docstring promises."""
    for gb in (8, 24, 80):
        n = calculate_matrix_size_from_memory(gb)
        needed = 3 * n * n * 4          # 3 matrices, 4 bytes per FP32 element
        budget = gb * 1024 ** 3 / 10
        # Rounding to the nearest power of two can overshoot by up to 2x.
        assert needed <= budget * 2, f"{gb}GB: {n} needs {needed} vs budget {budget}"
