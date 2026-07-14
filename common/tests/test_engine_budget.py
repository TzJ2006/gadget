"""Unit tests for the VRAM-budgeting helpers in common.engine.

Pure functions — no torch, no CUDA, no model load. Run from repo root:
    python -m pytest common/tests/test_engine_budget.py
"""

from types import SimpleNamespace

from common.engine import kv_bytes_per_token, plan_token_budget_batches


# ── plan_token_budget_batches ──────────────────────────────────
def test_groups_respect_area_and_preserve_order():
    # max(len)=10, so 2×10=20<=25 fits, 3×10=30>25 doesn't → groups of 2.
    groups = plan_token_budget_batches([10, 10, 10, 10], max_area=25, reserve=0)
    assert groups == [[0, 1], [2, 3]]


def test_padding_uses_longest_in_group():
    # area = count × max(len): a long prompt inflates the whole group's padding.
    # [5,20,5]: 0 alone (next would be 2×20=40>30); 1 alone; 2 alone → all split.
    groups = plan_token_budget_batches([5, 20, 5], max_area=30, reserve=0)
    assert groups == [[0], [1], [2]]
    assert [i for g in groups for i in g] == [0, 1, 2]  # every index, in order

    # but short prompts of equal length pack together: 3×5=15<=30, 4th → 20<=30.
    assert plan_token_budget_batches([5, 5, 5, 5], max_area=30, reserve=0) == [[0, 1, 2, 3]]


def test_reserve_is_added_to_each_length():
    # eff = len + reserve = 10 each; 1×10<=12 but 2×10=20>12 → singletons.
    groups = plan_token_budget_batches([5, 5], max_area=12, reserve=5)
    assert groups == [[0], [1]]


def test_single_oversized_prompt_still_gets_a_group():
    # One prompt bigger than the whole budget must not be dropped.
    assert plan_token_budget_batches([100], max_area=10, reserve=0) == [[0]]


def test_empty_input():
    assert plan_token_budget_batches([], max_area=100, reserve=0) == []


# ── kv_bytes_per_token ─────────────────────────────────────────
def test_kv_bytes_basic():
    cfg = SimpleNamespace(
        num_hidden_layers=2, hidden_size=8, num_attention_heads=4, num_key_value_heads=2
    )
    # head_dim = 8/4 = 2; 2(K,V) × 2 layers × 2 kv × 2 head_dim × 2 bytes = 32
    assert kv_bytes_per_token(cfg) == 32


def test_kv_bytes_defaults_kv_heads_to_attention_heads():
    cfg = SimpleNamespace(num_hidden_layers=1, hidden_size=8, num_attention_heads=4)
    # no num_key_value_heads → falls back to 4; head_dim=2; 2×1×4×2×2 = 32
    assert kv_bytes_per_token(cfg) == 32


def test_kv_bytes_returns_none_when_config_incomplete():
    assert kv_bytes_per_token(SimpleNamespace()) is None
    assert kv_bytes_per_token(SimpleNamespace(num_hidden_layers=2)) is None
