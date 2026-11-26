"""The per-source usage chart reaches the report at all three levels.

The chart chain was fully built and fully unreachable: charts.generate_daily_chart
had direct unit tests and looked covered, but _generate_chart in weekly_summary
and monthly_summary had no callers, so no PNG was ever produced — while three
places went on probing for the file and one copied it into the site. Direct
tests on a function say nothing about whether anything calls it.

These pin reachability rather than rendering: the chart is generated, its name
is referenced by the markdown, and the path is handed to the publisher that
copies it into static/. matplotlib is not required — charts is patched out.
"""

from datetime import date
from pathlib import Path
from unittest.mock import patch

from summarize import daily_merge, formatter, monthly_summary, weekly_summary

PNG = Path("/tmp/outputs/images/summarize/2026-06-13-usage.png")


# ─── the markdown side ───────────────────────────────────────────────

def test_daily_markdown_links_the_chart():
    report = {"token_usage_by_source": {"claude_code": {"totals": {"totalTokens": 5}}}}
    md = formatter.generate_markdown(report, date(2026, 6, 13),
                                     chart_filename="2026-06-13-usage.png")
    assert "![AI Usage · 2026-06-13](/images/daily/2026-06-13-usage.png)" in md


def test_daily_markdown_has_no_image_without_a_chart():
    report = {"token_usage_by_source": {"claude_code": {"totals": {"totalTokens": 5}}}}
    md = formatter.generate_markdown(report, date(2026, 6, 13))
    assert "/images/daily/" not in md


def test_weekly_markdown_links_the_chart():
    report = {
        "week": "2026-W24",
        "date_range": {"start": "2026-06-08", "end": "2026-06-14"},
        "combined_token_usage_summary": {"totals": {"totalTokens": 9, "totalCost": 1.0}},
        "token_usage_by_source_summary": {"claude_code": {"totals": {"totalTokens": 9}}},
    }
    md = weekly_summary.generate_weekly_markdown(
        report, 2026, 24, chart_filename="2026-06-08-usage.png")
    assert "(/images/weekly/2026-06-08-usage.png)" in md


def test_monthly_markdown_links_the_chart():
    report = {
        "month": "2026-06",
        "combined_token_usage_summary": {"totals": {"totalTokens": 9, "totalCost": 1.0}},
        "token_usage_by_source_summary": {"claude_code": {"totals": {"totalTokens": 9}}},
    }
    md = monthly_summary.generate_monthly_markdown(
        report, 2026, 6, chart_filename="2026-06-01-usage.png")
    assert "(/images/monthly/2026-06-01-usage.png)" in md


# ─── the reachability side: something actually calls the generator ───

def test_weekly_generate_produces_and_publishes_the_chart():
    seen = {}

    def fake_post(markdown_body, iso_year, iso_week, hugo_site, **kw):
        seen["chart_path"] = kw.get("chart_path")
        seen["markdown"] = markdown_body
        return Path("post.md")

    with patch.object(weekly_summary, "_generate_chart", return_value=PNG) as gen, \
         patch.object(weekly_summary, "generate_weekly_hugo_post", side_effect=fake_post), \
         patch.object(weekly_summary, "save_weekly_report"), \
         patch.object(weekly_summary, "run_hugo_update"), \
         patch.object(weekly_summary, "require_hugo_site", return_value=Path("site")):
        _run_weekly_generate()

    assert gen.call_count == 1, "nothing called the chart generator"
    assert seen["chart_path"] == PNG, "chart never reached the publisher"
    assert PNG.name in seen["markdown"], "chart never referenced by the markdown"


def _run_weekly_generate():
    """Drive cmd_generate with everything upstream of rendering stubbed out."""
    import argparse

    args = argparse.Namespace(week="2026-W24", api="ollama", deploy=True,
                              force=True, no_cache=True, timeout=1,
                              overwrite_human=False)
    with patch.object(weekly_summary, "resolve_reports_dir", return_value=Path("/tmp/r")), \
         patch.object(weekly_summary, "load_weekly_reports",
                      return_value=[{"date": "2026-06-08"}]), \
         patch.object(weekly_summary, "run_cached_period_llm",
                      return_value={"summary": "s"}), \
         patch.object(weekly_summary, "collect_usage_by_source",
                      return_value={"claude_code": {"totals": {"totalTokens": 9}}}), \
         patch.object(weekly_summary, "compute_weekly_statistics", return_value={}), \
         patch.object(weekly_summary, "combine_usage_summaries",
                      return_value={"totals": {"totalTokens": 9, "totalCost": 1.0}}):
        weekly_summary.cmd_generate(args)


def _calls_within(module, func_name: str) -> set[str]:
    """Names called inside `func_name` of `module`, read from its real source."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return {
                (n.func.id if isinstance(n.func, ast.Name) else
                 n.func.attr if isinstance(n.func, ast.Attribute) else "")
                for n in ast.walk(node) if isinstance(n, ast.Call)
            }
    raise AssertionError(f"{module.__name__}.{func_name} not found")


def test_every_level_actually_calls_its_chart_generator():
    """The invariant that broke: the function existed, nothing called it.

    Read from the production source, so deleting the call fails this test —
    which a direct unit test of the generator never would.
    """
    assert "generate_daily_chart" in _calls_within(daily_merge, "cmd_merge")
    assert "_generate_chart" in _calls_within(weekly_summary, "cmd_generate")
    assert "_generate_chart" in _calls_within(monthly_summary, "cmd_generate")


def test_every_level_forwards_the_chart_to_its_publisher():
    """And the path reaches the publisher that copies it into static/."""
    import ast
    import inspect

    for module, cmd in ((daily_merge, "cmd_merge"),
                        (weekly_summary, "cmd_generate"),
                        (monthly_summary, "cmd_generate")):
        tree = ast.parse(inspect.getsource(module))
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == cmd:
                for call in ast.walk(node):
                    if isinstance(call, ast.Call) and any(
                            kw.arg == "chart_path" for kw in call.keywords):
                        found = True
        assert found, f"{module.__name__}.{cmd} never passes chart_path on"
