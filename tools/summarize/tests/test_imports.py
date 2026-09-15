"""Migration smoke test — verifies all external import contracts survive the refactor.

Run BEFORE and AFTER the split to ensure nothing broke.

The daily_summary groups are gone with the shim they guarded. They asserted two
consumers: mcp_server.py, which is not in this repository and never has been,
and monthly/weekly, which do not import it (grep both files -- they reach for
common/ and summarize submodules directly). weekly_summary and monthly_summary
remain real implementations, so their contracts below still mean something.
"""

import importlib
import pytest


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
