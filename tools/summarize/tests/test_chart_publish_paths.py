"""The usage chart survives the trip from outputs/ to the published page.

Wiring the chart in (4faab70) created three ways for it to go missing that the
reachability tests in test_usage_chart_wired.py cannot see, because each is
about a *path* rather than a call:

  1. all three levels wrote to one directory keyed by a date, so 2026-06-01's
     daily chart and 2026-06's monthly chart were the same file;
  2. the replay deploy path (`summarize daily deploy`, the step `auto --deploy`
     ends on) published the link without copying the PNG;
  3. static/images/daily was not in the sync map, so the PNG existed only on
     the machine that merged that day -- and the next publish elsewhere would
     stage its deletion, the way /dag/ deleted itself.

Pure-mock: no matplotlib, no rclone, no site.
"""

import ast
import inspect
from datetime import date
from pathlib import Path

from summarize import charts, daily_deploy


# ─── 1. levels must not share a filename ─────────────────────────────

def test_each_level_gets_its_own_directory():
    dirs = [charts.chart_dir_for(lvl) for lvl in charts.CHART_LEVELS]
    assert len(set(dirs)) == len(dirs), f"levels share a directory: {dirs}"


def test_the_colliding_dates_no_longer_collide():
    """June 1st 2026 is a Monday: daily, weekly and monthly all key on it."""
    june1 = date(2026, 6, 1)
    paths = {lvl: charts.chart_path_for(lvl, june1) for lvl in charts.CHART_LEVELS}
    assert len(set(paths.values())) == 3, f"still colliding: {paths}"
    # and the basename is deliberately the same -- it is the directory that
    # separates them, which is what makes the site-side subdir match.
    assert len({p.name for p in paths.values()}) == 1


def test_an_unknown_level_is_refused():
    try:
        charts.chart_dir_for("quarterly")
    except ValueError:
        return
    raise AssertionError("an unknown level must not silently get a directory")


def test_generator_and_lookup_agree_on_the_filename():
    """The deploy paths find the chart by recomputing its path."""
    d = date(2026, 6, 13)
    assert charts.chart_path_for("weekly", d).name == charts.chart_filename(d)
    assert charts.chart_path_for("weekly", d).parent == charts.chart_dir_for("weekly")


# ─── 2. the replay deploy path must carry the PNG ────────────────────

def _kwargs_of_call(func, callee):
    tree = ast.parse(inspect.getsource(func))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name == callee:
                return {kw.arg for kw in node.keywords}
    raise AssertionError(f"{func.__name__} never calls {callee}")


def test_daily_deploy_hands_the_chart_to_the_publisher():
    """Without chart_path the publisher copies nothing and the link 404s.

    The saved markdown already contains the link, so this is not optional --
    weekly and monthly both do the lookup before their deploy call.
    """
    kwargs = _kwargs_of_call(daily_deploy.cmd_deploy, "generate_hugo_post")
    assert "chart_path" in kwargs, (
        "daily deploy publishes the chart link but not the PNG; "
        f"it passes only {sorted(kwargs)}")


def test_daily_deploy_looks_the_chart_up_in_the_daily_namespace():
    src = inspect.getsource(daily_deploy.cmd_deploy)
    assert 'chart_path_for("daily"' in src, (
        "daily deploy must resolve the chart through charts.chart_path_for, "
        "not by rebuilding the path itself")


# ─── 3. every published level must be synced ─────────────────────────

def test_every_chart_level_has_a_sync_entry():
    """A published static namespace that is not synced deletes itself.

    static/images/ is gitignored and publish.py rebuilds public/ from static/,
    so a machine without the PNGs stages their deletion on the next publish.
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))
    import sync

    synced = {local for local, _remote in sync.SYNC_DIRS["website"]}
    missing = [lvl for lvl in charts.CHART_LEVELS
               if f"tools/website/static/images/{lvl}" not in synced]
    assert not missing, (
        f"published but never synced: {missing} -- these PNGs would exist only "
        "on the machine that generated them")
