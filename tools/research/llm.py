"""LLM abstraction for the researcher profiler — calls LLM via common/ backends."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from common.llm import call_llm_raw
from common.io import atomic_write, content_hash as _content_hash
from common.json_utils import try_parse_json, repair_json_with_llm
from research.cache import DiskCache

logger = logging.getLogger(__name__)


def call_llm(
    prompt: str,
    model: str = "sonnet",
    cache: DiskCache | None = None,
    no_cache: bool = False,
    backend: str = "ollama",
    timeout: int = 300,
) -> str:
    """Call LLM and return the response text.

    Thin cache wrapper around ``common.llm.call_llm_raw``. Used by the profiler
    and by scout evaluation (via ``call_scout_llm``).

    Backends:
        ollama (default)     — local Ollama server (OpenAI protocol, keyless)
        claude_cli           — calls `claude --print --model <model> -p <prompt>`
        anthropic            — uses anthropic Python SDK (needs ANTHROPIC_API_KEY)
        openai               — uses openai Python SDK (needs OPENAI_API_KEY)
    """
    hash_val = _content_hash(f"{backend}:{model}:{prompt}")
    cache_key = f"llm:{hash_val}"

    if cache and not no_cache:
        cached = cache.get("llm", cache_key)
        if cached is not None:
            logger.info("[LLM] 缓存命中")
            return cached

    response = call_llm_raw(prompt, backend=backend, model=model, timeout=timeout)

    if cache and response:
        cache.put("llm", cache_key, response)

    return response


def _save_failed_response(text: str) -> None:
    """Save raw LLM response to log file for debugging."""
    from common.paths import LOGS_DIR
    log_dir = LOGS_DIR / "research" / "json_repair_failed"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"{timestamp}.txt"
    try:
        atomic_write(log_file, text)
        logger.info("[LLM] 已保存失败响应到 %s", log_file)
    except Exception as e:
        logger.warning("[LLM] 保存失败响应出错: %s", e)


def parse_json_response(text: str, backend: str = "ollama") -> dict[str, Any]:
    """Extract and parse JSON from LLM response text.

    Stages 1-3 (non-LLM) then escalating LLM repair (haiku → sonnet → opus), both
    delegated to common.json_utils. Profiler-specific: a larger repair payload cap
    (20K) and failed-response logging for debugging.

    Args:
        backend: LLM backend for the repair call (ollama/claude_cli/anthropic/openai).
            Defaults to "ollama".
    """
    result = try_parse_json(text)
    if result is not None:
        return result

    # timeout=300 matches the old inline loop (call_llm_raw's default); common's
    # repair default of 120s is too tight for a 20K payload on a local model.
    repaired = repair_json_with_llm(text, backend, strategy="escalating",
                                    max_chars=20000, timeout=300)
    if repaired is not None:
        return repaired

    _save_failed_response(text)
    logger.error("[LLM] 所有模型修复 JSON 均失败，已保存原始响应到日志")
    return {}
