"""Publish benchmark reports into the Hugo site (content/ + static/)."""

from __future__ import annotations

from pathlib import Path

from common.site_staging import copy_site_static, write_site_content


def stage_benchmark_report(report_html: str | Path, hugo_site: Path) -> tuple[Path, Path]:
    """Publish the benchmark HTML report and its wrapper page into the Hugo site."""
    report_path = Path(report_html)
    if not report_path.exists():
        raise FileNotFoundError(report_path)

    staged_report = copy_site_static(
        hugo_site,
        report_path,
        Path("benchmark-report") / "report.html",
    )

    wrapper = f"""---
title: "Benchmark"
date: 2026-01-01T00:00:00-05:00
summary: "Cross-platform CPU/GPU benchmark leaderboard and historical report."
draft: false
---

The latest benchmark leaderboard is published below.

[Open the full HTML report](/benchmark-report/report.html)

<div style="margin-top: 1.5rem; border: 1px solid rgba(128, 128, 128, 0.25); border-radius: 12px; overflow: hidden;">
  <iframe
    src="/benchmark-report/report.html"
    title="Benchmark report"
    style="width: 100%; min-height: 85vh; border: 0; background: white;"
    loading="lazy"></iframe>
</div>
"""
    wrapper_path = write_site_content(
        hugo_site,
        Path("benchmark.md"),
        wrapper,
    )
    return wrapper_path, staged_report
