"""Migration smoke test — verifies all external import contracts survive the refactor.

Run BEFORE and AFTER the split to ensure nothing broke.
"""

import importlib
import pytest


# ── Symbols that mcp_server.py imports from daily_summary ──────────────
DAILY_SUMMARY_SYMBOLS = [
    "discover_all_dates",
    "_resolve_output_dir",
    "collect_conversations",
    "_get_device_name",
    "_atomic_write",
    "_call_summarize",
    "_sort_report_by_importance",
    "generate_markdown",
    "save_report",
    "MERGE_PROMPT_PREFIX",
    "SUMMARY_PROMPT",
    "MERGE_DEVICE_SUMMARY_PREFIX",
    "ChunkTimeoutError",
    "load_ccusage_for_date",
    "_merge_token_usages",
]

# ── Symbols that monthly_summary.py / weekly_summary.py import ─────────
DAILY_SHARED_SYMBOLS = [
    "_atomic_write",
    "_resolve_output_dir",
    "_load_config",
    "run_hugo_update",
]

MONTHLY_SYMBOLS = [
    "format_reports_for_llm",
    "aggregate_token_usage",
    "combine_usage_summaries",
    "_has_usage_data",
    "_compute_source_hash",
]

WEEKLY_SYMBOLS = [
    "_parse_week",
    "_week_str",
    "_week_date_range",
    "load_weekly_reports",
    "compute_weekly_statistics",
    "_call_weekly_summarize_chunked",
    "_load_weekly_cache",
    "_save_weekly_cache",
    "_cache_dir",
    "generate_weekly_markdown",
    "save_weekly_report",
]

LLM_BACKENDS_SYMBOLS = [
    "LLMCallConfig",
    "call_llm",
    "parse_json_response",
    "repair_json_with_llm",
    "try_repair_result",
    "ChunkTimeoutError",
    "chunk_text",
    "timed_llm_call",
    "load_chunk_cache",
    "save_chunk_cache",
    "cleanup_chunk_cache",
    "hierarchical_merge",
]


@pytest.mark.parametrize("symbol", DAILY_SUMMARY_SYMBOLS)
def test_daily_summary_exports(symbol):
    """mcp_server.py depends on these symbols from daily_summary."""
    mod = importlib.import_module("summarize.daily_summary")
    assert hasattr(mod, symbol), f"daily_summary missing: {symbol}"


@pytest.mark.parametrize("symbol", DAILY_SHARED_SYMBOLS)
def test_daily_shared_exports(symbol):
    """monthly/weekly depend on these symbols from daily_summary."""
    mod = importlib.import_module("summarize.daily_summary")
    assert hasattr(mod, symbol), f"daily_summary missing: {symbol}"


@pytest.mark.parametrize("symbol", MONTHLY_SYMBOLS)
def test_monthly_exports(symbol):
    """weekly_summary and mcp_server depend on these from monthly_summary."""
    mod = importlib.import_module("summarize.monthly_summary")
    assert hasattr(mod, symbol), f"monthly_summary missing: {symbol}"


@pytest.mark.parametrize("symbol", WEEKLY_SYMBOLS)
def test_weekly_exports(symbol):
    """mcp_server depends on these from weekly_summary."""
    mod = importlib.import_module("summarize.weekly_summary")
    assert hasattr(mod, symbol), f"weekly_summary missing: {symbol}"


@pytest.mark.parametrize("symbol", LLM_BACKENDS_SYMBOLS)
def test_llm_backends_exports(symbol):
    """monthly/weekly depend on these from llm_backends."""
    mod = importlib.import_module("summarize.llm_backends")
    assert hasattr(mod, symbol), f"llm_backends missing: {symbol}"
