"""Automated daily → weekly → monthly pipeline.

Runs the full summarize pipeline:
1. Daily export (all unexported dates)
2. Daily merge (--sync-all)
3. Weekly generate (all missing weekly reports)
4. Monthly generate (all missing monthly reports)

Usage:
    python -m summarize auto
    python -m summarize auto --deploy
    python -m summarize auto --api anthropic
    python -m summarize auto --workers 4
    python -m summarize auto --date 2026-04-19   # override "yesterday"
"""

import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from common.paths import REPORTS_DIR
from .onboarding import ensure_auto_ready

_DEFAULT_REPORTS_DIR = REPORTS_DIR / "summarize"


def _unload_ollama() -> None:
    """Free Ollama VRAM (all resident models, incl. qwen) once the pipeline is done.

    Historically the chat model was evicted mid-pipeline as a side effect of the
    translation-model swap thrash; with co-residency (translation num_ctx 8192)
    both models now survive the run, so the 23GB chat model would otherwise sit
    on the GPU until its idle timeout, and the translator up to keep_alive=30m.
    GADGET_KEEP_OLLAMA=1 skips (e.g. cron back-to-back runs).
    """
    from common.engine import _free_ollama_vram  # lazy: stdlib-only helper

    _free_ollama_vram()
    print("[auto] Ollama models unloaded (set GADGET_KEEP_OLLAMA=1 to keep them warm)")


def _run(cmd: list[str]) -> bool:
    print(f"\n{'='*60}")
    print(f"[auto] {' '.join(cmd)}")
    print(f"{'='*60}")
    t0 = time.monotonic()
    result = subprocess.run(cmd)
    elapsed = time.monotonic() - t0
    if result.returncode != 0:
        print(f"[auto] exited {result.returncode} after {elapsed:.0f}s, continuing...")
        return False
    print(f"[auto] step finished in {elapsed:.0f}s")
    return True


def _find_missing_weeks(reports_dir: Path) -> list[str]:
    """Scan daily reports and return week labels without a weekly report."""
    weeks: dict[str, list[str]] = {}
    for f in sorted(reports_dir.glob("????-??-??.json")):
        if "monthly" in f.stem or "weekly" in f.stem:
            continue
        try:
            d = date.fromisoformat(f.stem)
        except ValueError:
            continue
        iso_year, iso_week, _ = d.isocalendar()
        week_key = f"{iso_year:04d}-W{iso_week:02d}"
        weeks.setdefault(week_key, []).append(f.stem)

    today = date.today()
    missing = []
    for week_key in sorted(weeks):
        parts = week_key.upper().split("-W")
        iso_year, iso_week = int(parts[0]), int(parts[1])
        sunday = date.fromisocalendar(iso_year, iso_week, 7)
        if sunday >= today:
            continue
        weekly_json = reports_dir / f"{week_key}-weekly.json"
        if not weekly_json.exists() or _stale(weekly_json, weeks[week_key], reports_dir):
            missing.append(week_key)
    return missing


def _stale(agg_json: Path, daily_stems: list[str], reports_dir: Path) -> bool:
    """True if any covered daily report was (re)generated after the aggregate."""
    agg_mtime = agg_json.stat().st_mtime
    return any((reports_dir / f"{s}.json").stat().st_mtime > agg_mtime
               for s in daily_stems if (reports_dir / f"{s}.json").exists())


def _find_missing_months(reports_dir: Path) -> list[str]:
    """Scan daily reports and return month labels without a monthly report."""
    months: dict[str, list[str]] = {}
    for f in sorted(reports_dir.glob("????-??-??.json")):
        if "monthly" in f.stem or "weekly" in f.stem:
            continue
        month_key = f.stem[:7]  # YYYY-MM
        months.setdefault(month_key, []).append(f.stem)

    today = date.today()
    missing = []
    for month_key in sorted(months):
        year, month = int(month_key[:4]), int(month_key[5:7])
        is_past = (year < today.year) or (year == today.year and month < today.month)
        if not is_past:
            continue
        monthly_json = reports_dir / f"{month_key}-monthly.json"
        if not monthly_json.exists() or _stale(monthly_json, months[month_key], reports_dir):
            missing.append(month_key)
    return missing


def cmd_auto(args) -> None:
    target = date.today() - timedelta(days=1)
    if args.date:
        try:
            target = date.fromisoformat(args.date)
        except ValueError:
            print(f"[error] Invalid date: {args.date}")
            sys.exit(1)

    if not getattr(args, "skip_onboard_check", False):
        ready = ensure_auto_ready(
            api=args.api,
            deploy=args.deploy,
            hugo_site=getattr(args, "hugo_site", None),
        )
        if not ready:
            sys.exit(2)

    print(f"[auto] Aggregation target: {target.isoformat()}")

    api_args = ["--api", args.api] if args.api else []
    deploy_args = ["--deploy"] if args.deploy else []
    hugo_args = []
    if args.deploy and getattr(args, "hugo_site", None):
        hugo_args = ["--hugo-site", args.hugo_site]
    force_args = ["--force"] if args.force else []
    workers = max(1, int(getattr(args, "workers", 1) or 1))
    workers_args = ["--workers", str(workers)]
    py = sys.executable

    # 1. Daily export (all unexported dates)
    _run([py, "-m", "summarize", "daily", "export"] + api_args + force_args)

    # 2. Daily merge (sync + merge all unfinalized dates, exclude today)
    today_str = date.today().isoformat()
    _run([py, "-m", "summarize", "daily", "merge", "--sync-all", "--before", today_str]
         + api_args + deploy_args + hugo_args + force_args + workers_args)

    # 2.5 Deploy backlog: merge --deploy only covers dates merged this run,
    # so run the dedicated deploy step to pick up any undeployed reports.
    if args.deploy:
        _run([py, "-m", "summarize", "daily", "deploy"] + hugo_args)

    # 3. Weekly: generate all completed weeks whose report is missing or
    #    older than a covered daily (re-merged dailies invalidate the aggregate)
    weeks_to_gen = _find_missing_weeks(_DEFAULT_REPORTS_DIR)
    if weeks_to_gen:
        print(f"\n[auto] Weekly reports to generate: {', '.join(weeks_to_gen)}")
        for week_str in weeks_to_gen:
            print(f"\n[auto] Generating weekly: {week_str}")
            _run([py, "-m", "summarize", "weekly", "generate", "--week", week_str, "--force"]
                 + api_args + deploy_args + hugo_args)
    else:
        print("\n[auto] All weekly reports up to date.")

    # 4. Monthly: same rule as weekly
    months_to_gen = _find_missing_months(_DEFAULT_REPORTS_DIR)
    if months_to_gen:
        print(f"\n[auto] Monthly reports to generate: {', '.join(months_to_gen)}")
        for month_str in months_to_gen:
            print(f"\n[auto] Generating monthly: {month_str}")
            _run([py, "-m", "summarize", "monthly", "generate", "--month", month_str, "--force"]
                 + api_args + deploy_args + hugo_args)
    else:
        print("\n[auto] All monthly reports up to date.")

    _unload_ollama()
    print(f"\n[auto] Pipeline complete.")
