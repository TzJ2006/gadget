#!/usr/bin/env python3
"""AI 对话日报总结工具 — backward-compatible re-export shim.

All implementations have moved to sub-modules (config, remote, parsers, usage,
summarizer, formatter, daily, cli).  This file re-exports every public symbol
so that existing ``from daily_summary import ...`` statements continue to work.

For new code, prefer importing from the specific sub-module directly:
    from summarize.config import _load_config
    from summarize.parsers import collect_conversations
"""

# ── common re-exports (used by monthly/weekly/mcp_server) ──────────────
from common.io import atomic_write as _atomic_write  # noqa: F401
from common.hugo import run_hugo_update  # noqa: F401
from common.llm import (  # noqa: F401
    LLMCallConfig,
    call_llm,
    ChunkTimeoutError,
    chunk_text,
    timed_llm_call,
    load_chunk_cache as _load_chunk_cache,
    save_chunk_cache as _save_chunk_cache,
    cleanup_chunk_cache as _cleanup_chunk_cache,
    hierarchical_merge,
)
from common.json_utils import (  # noqa: F401
    parse_json_response as _parse_json_response,
    repair_json_with_llm as _repair_json_with_llm,
    try_repair_result,
)
from common.paths import LOGS_DIR, REPORTS_DIR, CACHE_DIR  # noqa: F401
from common.site_staging import resolve_site_content_dir, write_site_content  # noqa: F401

_DEFAULT_LOGS_DIR = LOGS_DIR / "summarize"
_DEFAULT_REPORTS_DIR = REPORTS_DIR / "summarize"
_DEFAULT_CACHE_DIR = CACHE_DIR / "summarize"

# ── config ─────────────────────────────────────────────────────────────
from summarize.config import (  # noqa: F401
    _CONFIG_PATH,
    _load_config,
    _resolve_output_dir,
    _get_device_name,
)

# ── remote ─────────────────────────────────────────────────────────────
from summarize.remote import (  # noqa: F401
    _find_rclone,
    _rclone_upload,
    _rclone_download_logs,
)

# ── parsers ────────────────────────────────────────────────────────────
from summarize.parsers import (  # noqa: F401
    discover_all_dates,
    parse_claude_code,
    parse_chatgpt_export,
    parse_generic,
    parse_codex,
    collect_conversations,
)

# ── usage ──────────────────────────────────────────────────────────────
from summarize.usage import (  # noqa: F401
    _refresh_usage_snapshots,
    fetch_ccusage,
    save_ccusage_file,
    discover_sources,
    fetch_source_usage,
    save_usage_file,
    load_ccusage_for_date,
    _merge_token_usages,
    _extract_text_content,
)

# ── summarizer ─────────────────────────────────────────────────────────
from summarize.summarizer import (  # noqa: F401
    SUMMARY_PROMPT,
    MERGE_PROMPT_PREFIX,
    MERGE_DEVICE_SUMMARY_PREFIX,
    _build_summary_prompt,
    _format_conversation,
    _get_device_label,
    format_conversations,
    chunk_conversations,
    _call_summarize,
    _call_single_summarize,
)

# ── formatter ──────────────────────────────────────────────────────────
from summarize.formatter import (  # noqa: F401
    generate_markdown,
    _sort_report_by_importance,
    save_report,
    generate_hugo_post,
)

# ── daily pipeline ────────────────────────────────────────────────────
from summarize.daily import (  # noqa: F401
    cmd_export,
    cmd_export_past,
    cmd_merge,
    cmd_legacy,
    cmd_deploy,
    cmd_config,
)

# ── cli ────────────────────────────────────────────────────────────────
from summarize.cli import main  # noqa: F401

if __name__ == "__main__":
    main()
