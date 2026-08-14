"""Shared helpers for weekly and monthly period reports.

Period-specific prompts, tool schemas, and markdown live in weekly_summary /
monthly_summary. This module holds the copy-pasted pipeline: cache, chunked LLM
calls, Hugo frontmatter, argparse flags, and chart reshape.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Optional

from common.bilingual import write_bilingual
from common.io import atomic_write as _atomic_write
from common.llm import (
    DEFAULT_BACKEND,
    LLM_BACKENDS,
    LLMCallConfig,
    ChunkTimeoutError,
    chunk_text,
    timed_llm_call,
    load_chunk_cache as _load_chunk_cache,
    save_chunk_cache as _save_chunk_cache,
    cleanup_chunk_cache as _cleanup_chunk_cache,
    hierarchical_merge,
)
from common.paths import REPORTS_DIR, CACHE_DIR
from common.site_staging import resolve_site_content_dir, copy_site_static

from .config import _load_config, _resolve_output_dir, resolve_hugo_site


# ─── Named constants (A19=a); config keys override when present ────────

CHUNK_CHARS = 150_000
PROMPT_OVERHEAD = 200
TIMEOUT_DAILY = 600
TIMEOUT_WEEKLY = 900
TIMEOUT_MONTHLY = 1800

_LOW_THINKING = {"type": "enabled", "budget_tokens": 1024}

DEFAULT_REPORTS_DIR = REPORTS_DIR / "summarize"


def _cfg_int(*keys: str, default: int) -> int:
    """First positive int among config keys, else *default*."""
    cfg = _load_config()
    for key in keys:
        val = cfg.get(key)
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            continue
        parsed = int(val)
        if parsed > 0:
            return parsed
    return default


def resolved_chunk_chars() -> int:
    return _cfg_int("chunk_chars", "llm_chunk_chars", default=CHUNK_CHARS)


def resolved_timeout_daily() -> int:
    return _cfg_int("timeout_daily", default=TIMEOUT_DAILY)


def resolved_timeout_weekly() -> int:
    return _cfg_int("timeout_weekly", default=TIMEOUT_WEEKLY)


def resolved_timeout_monthly() -> int:
    return _cfg_int("timeout_monthly", default=TIMEOUT_MONTHLY)


# ─── Timezone (A7=c): local offset, not hardcoded -05:00 ───────────────

def local_tz_offset_str(when: Optional[datetime] = None) -> str:
    """Local UTC offset as ``±HH:MM`` (DST-aware for *when*)."""
    dt = (when or datetime.now()).astimezone()
    offset = dt.strftime("%z")  # +HHMM
    if not offset:
        return "+00:00"
    return offset[:3] + ":" + offset[3:]


def hugo_datetime(d: date, hour: int = 0, minute: int = 0, second: int = 0) -> str:
    """Hugo frontmatter datetime in the machine's local timezone."""
    local = datetime(d.year, d.month, d.day, hour, minute, second).astimezone()
    return local.strftime("%Y-%m-%dT%H:%M:%S") + local_tz_offset_str(local)


def _yaml_escape(text: str) -> str:
    return (text.replace("\\", "\\\\").replace('"', '\\"')
            .replace("\r", " ").replace("\n", " "))


def summary_from_markdown(markdown_body: str, fallback: str) -> str:
    summary = fallback
    for line in markdown_body.splitlines():
        if line.startswith("> "):
            summary = line[2:].strip()
            break
    return _yaml_escape(summary)


def generate_period_hugo_post(
    markdown_body: str,
    hugo_site: Path,
    *,
    title: str,
    post_date: date,
    keywords: list[str],
    fallback_summary: str,
    content_parts: tuple[str, ...],
    filename: str,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
    chart_path: Optional[Path] = None,
    chart_image_subdir: Optional[str] = None,
    api: str = DEFAULT_BACKEND,
    force: bool = False,
    overwrite_human: bool = False,
    engine=None,
    pbar=None,
) -> Path:
    """Write a bilingual Hugo bugJournal (or similar) post via write_bilingual.

    ``api`` is unused (translation is local-inference); kept so call sites that
    still pass it do not break.
    """
    _ = api
    summary = summary_from_markdown(markdown_body, fallback_summary)
    kw_yaml = "\n".join(f"- {k}" for k in keywords)
    stamp = hugo_datetime(post_date, hour=hour, minute=minute, second=second)
    frontmatter = f"""---
title: "{_yaml_escape(title)}"
date: {stamp}
keywords:
{kw_yaml}
summary: "{summary}"
draft: false
---

"""
    resolve_site_content_dir(hugo_site, *content_parts)

    if chart_path and chart_path.exists():
        subdir = chart_image_subdir or content_parts[-1]
        dest = copy_site_static(
            hugo_site, chart_path,
            Path("images") / subdir / chart_path.name, force=force)
        print(f"[ok] Chart copied to Hugo: {dest}")

    rel = Path(*content_parts) / filename
    en_path, zh_path = write_bilingual(
        hugo_site, rel, frontmatter + markdown_body,
        engine=engine, pbar=pbar, force=force,
        overwrite_human=overwrite_human)

    print(f"[ok] Hugo post generated: {en_path}")
    if zh_path:
        print(f"[ok] Hugo post (translated): {zh_path}")
    return en_path


# ─── Cache ─────────────────────────────────────────────────────────────

def period_cache_dir(kind: str) -> Path:
    return CACHE_DIR / "summarize" / kind


def compute_source_hash(daily_reports: list[dict]) -> str:
    """SHA-256 of source daily JSON (sorted by date; skip ``_`` temp fields)."""
    hasher = hashlib.sha256()
    for report in sorted(daily_reports, key=lambda r: r.get("date", "")):
        clean = {k: v for k, v in report.items() if not k.startswith("_")}
        hasher.update(json.dumps(clean, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return hasher.hexdigest()[:16]


def load_period_cache(cache_dir: Path, label: str, source_hash: str) -> Optional[dict]:
    """Load a period LLM cache. None = miss or stale source hash."""
    cache_file = cache_dir / f"{label}.json"
    if not cache_file.exists():
        return None
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    if data.get("_cache_meta", {}).get("source_hash") != source_hash:
        return None
    data.pop("_cache_meta", None)
    print(f"[info] Cache hit ({cache_file.name})")
    return data


def save_period_cache(cache_dir: Path, label: str, result: dict,
                      source_hash: str) -> None:
    cache = {**result, "_cache_meta": {
        "source_hash": source_hash,
        "cached_at": datetime.now().isoformat(),
    }}
    try:
        _atomic_write(cache_dir / f"{label}.json",
                      json.dumps(cache, ensure_ascii=False, indent=2))
    except OSError as e:
        print(f"[warn] Cache write failed: {e}")


def run_cached_period_llm(
    *,
    cache_dir: Path,
    label: str,
    daily_reports: list[dict],
    no_cache: bool,
    force: bool,
    call_llm_fn: Callable[[Optional[Path]], dict],
) -> dict:
    """Cache check → LLM → save global cache → cleanup chunk cache."""
    source_hash = compute_source_hash(daily_reports)
    llm_result = None
    if not no_cache and not force:
        llm_result = load_period_cache(cache_dir, label, source_hash)

    chunk_cache_dir = cache_dir / "chunks" / label
    if llm_result is None:
        if not no_cache:
            chunk_cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            llm_result = call_llm_fn(None if no_cache else chunk_cache_dir)
        except ChunkTimeoutError as e:
            print(f"[error] {e}")
            sys.exit(1)
        save_period_cache(cache_dir, label, llm_result, source_hash)
        _cleanup_chunk_cache(chunk_cache_dir)
    return llm_result


# ─── Chunked LLM ───────────────────────────────────────────────────────

def call_period_summarize_chunked(
    api: str,
    daily_reports: list[dict],
    *,
    summary_prompt: str,
    merge_prompt: str,
    build_config: Callable[[str], LLMCallConfig],
    timeout: int,
    format_reports: Callable[[list[dict]], str],
    make_groups: Callable[[list[dict]], list[list[dict]]],
    target_line: str,
    chunk_cache_dir: Optional[Path] = None,
) -> dict:
    """Single timed call, or group → chunk_text → hierarchical_merge."""
    max_chars = resolved_chunk_chars()
    full_text = format_reports(daily_reports)
    prompt_overhead = len(summary_prompt) + PROMPT_OVERHEAD
    suffix = f"\n\n{target_line}"

    if len(full_text) + prompt_overhead <= max_chars:
        config = build_config(summary_prompt + full_text + suffix)
        return timed_llm_call(api, config, chunk_idx=1, total=1)

    groups = [g for g in make_groups(daily_reports) if g]
    text_groups = [format_reports(g) for g in groups]
    text_chunks = chunk_text(text_groups, max_chars=max_chars - prompt_overhead)

    n = len(text_chunks)
    print(f"[info] {len(full_text):,} chars, split into {n} chunks "
          f"(per-chunk timeout {timeout}s, total ~{timeout * n}s)...")

    global_hash = compute_source_hash(daily_reports) if chunk_cache_dir else None

    partial_summaries = []
    cache_hits = 0
    for i, chunk_texts in enumerate(text_chunks):
        chunk_content = "\n".join(chunk_texts)

        if chunk_cache_dir and global_hash:
            c_hash = hashlib.sha256(chunk_content.encode("utf-8")).hexdigest()[:16]
            cached = _load_chunk_cache(chunk_cache_dir, c_hash, global_hash, n)
            if cached is not None:
                cache_hits += 1
                print(f"[info] Chunk {i+1}/{n} cache hit ({len(chunk_content):,} chars)")
                partial_summaries.append(cached)
                continue

        print(f"[info] Summarizing chunk {i+1}/{n} ({len(chunk_content):,} chars)...")
        config = build_config(summary_prompt + chunk_content + suffix)
        result = timed_llm_call(api, config, chunk_idx=i + 1, total=n)
        partial_summaries.append(result)

        if chunk_cache_dir and global_hash:
            _save_chunk_cache(chunk_cache_dir, c_hash, result, global_hash, n)

    if cache_hits:
        print(f"[info] Chunk cache stats: {cache_hits}/{n} hits, "
              f"{n - cache_hits} API calls")

    if len(partial_summaries) == 1:
        return partial_summaries[0]

    def _merge_config(prompt_text: str) -> LLMCallConfig:
        return build_config(prompt_text)

    return hierarchical_merge(api, partial_summaries, merge_prompt,
                              _merge_config, timeout)


# ─── Chart reshape ─────────────────────────────────────────────────────

def reshape_usage_for_chart(usage_by_source: dict) -> dict:
    chart_input = {}
    for source, summary in (usage_by_source or {}).items():
        totals = summary.get("totals", {})
        if not totals:
            continue
        chart_input[source] = {
            "totals": totals,
            "modelBreakdowns": [{"modelName": n, **v}
                                for n, v in summary.get("model_breakdown", {}).items()],
        }
    return chart_input


def generate_period_chart(usage_by_source: dict, chart_date: date) -> Optional[Path]:
    chart_input = reshape_usage_for_chart(usage_by_source)
    if not chart_input:
        return None
    from .charts import generate_daily_chart
    from common.paths import IMAGES_DIR
    return generate_daily_chart(chart_input, chart_date,
                                output_dir=IMAGES_DIR / "summarize")


def collect_usage_by_source(daily_reports: list[dict]) -> dict:
    from .monthly_summary import aggregate_token_usage
    sources: set[str] = set()
    for r in daily_reports:
        sources.update((r.get("token_usage_by_source") or {}).keys())
        if r.get("token_usage"):
            sources.add("claude_code")
        if r.get("codex_token_usage"):
            sources.add("codex")
    return {s: aggregate_token_usage(daily_reports, source=s) for s in sorted(sources)}


# ─── CLI / argparse ────────────────────────────────────────────────────

def resolve_period_api(args) -> str:
    return getattr(args, "api", None) or _load_config().get("default_api") or DEFAULT_BACKEND


def resolve_reports_dir(args) -> Path:
    return _resolve_output_dir(
        getattr(args, "output", None),
        "SUMMARIZE_REPORTS_DIR",
        "reports_dir",
        DEFAULT_REPORTS_DIR,
    )


def require_hugo_site(args) -> Path:
    hugo_site = resolve_hugo_site(getattr(args, "hugo_site", None))
    if not hugo_site.exists():
        print(f"[error] Hugo site directory not found: {hugo_site}")
        sys.exit(1)
    return hugo_site


def add_api_argument(parser) -> None:
    parser.add_argument(
        "--api", type=str, choices=list(LLM_BACKENDS), default=None,
        help=f"LLM API (default: config default_api, else {DEFAULT_BACKEND})",
    )


def add_generate_arguments(parser, *, timeout_default: int) -> None:
    add_api_argument(parser)
    parser.add_argument("--output", type=str, default=None,
                        help="Reports directory (default: outputs/reports/summarize/)")
    parser.add_argument("--deploy", action="store_true",
                        help="Also deploy to Hugo site")
    parser.add_argument("--hugo-site", type=str, default=str(resolve_hugo_site()),
                        help="Hugo site root directory")
    parser.add_argument("--timeout", type=int, default=timeout_default,
                        help=f"LLM call timeout in seconds (default: {timeout_default})")
    parser.add_argument("--no-cache", action="store_true",
                        help="Skip LLM cache, force re-call API")
    parser.add_argument("--force", action="store_true",
                        help="Ignore existing output, force regeneration")
    parser.add_argument("--overwrite-human", action="store_true",
                        help="DANGEROUS: allow overwriting hand-written site files")


def add_deploy_arguments(parser) -> None:
    parser.add_argument("--output", type=str, default=None,
                        help="Reports directory (default: outputs/reports/summarize/)")
    parser.add_argument("--hugo-site", type=str, default=str(resolve_hugo_site()),
                        help="Hugo site root directory")
    parser.add_argument("--force", action="store_true",
                        help="Redeploy already-deployed reports (backs up first)")
    parser.add_argument("--overwrite-human", action="store_true",
                        help="DANGEROUS: allow overwriting hand-written site files")
