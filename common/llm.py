"""Unified LLM calling layer — raw text calls and structured JSON calls.

Two tiers:
  - ``call_llm_raw()`` — returns raw text, for simple prompt→text use cases
  - ``call_llm()`` / ``call_anthropic()`` etc. — returns parsed JSON dict,
    with SDK-specific features (tool_use, response_format, etc.)
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from common.io import atomic_write
from common.json_utils import parse_json_response, try_repair_result

logger = logging.getLogger(__name__)

# ─── Model constants ──────────────────────────────────────────────────

ANTHROPIC_MODELS = {
    "sonnet": "claude-sonnet-5",
    "opus": "claude-opus-4-8",
    "haiku": "claude-haiku-4-5-20251001",
}

OPENAI_MODELS = {
    "sonnet": "gpt-4o",
    "opus": "gpt-4o",
    "haiku": "gpt-4o-mini",
}

# Local Ollama speaks the OpenAI protocol, so the ``ollama`` backend reuses the
# same HTTP path — it differs only in config: a local default, a keyless
# client, and its own model/base-url env vars (falling back to OPENAI_* for
# back-compat with older setups that exported those).
# 127.0.0.1, NOT localhost: on Windows, localhost resolves IPv6-first and stalls
# ~2s per request before falling back to IPv4 (measured in
# test/performance/results/localhost_overhead.json — 2.05s vs 0.02s connect).
OLLAMA_DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"

# The default backend for every chat/reasoning call (summarize, research). Ollama
# runs Qwen3.6-35B locally; override per-call with --api / config default_api, or
# globally with GADGET_LLM_BACKEND.
# `... or "ollama"` (not a default arg) so an exported-but-empty env falls back to
# the real default rather than tripping the unknown-backend guard below.
DEFAULT_BACKEND = os.environ.get("GADGET_LLM_BACKEND") or "ollama"

# Single source of truth for valid chat backends. Both dispatchers validate against
# this so a typo'd config `default_api` / GADGET_LLM_BACKEND fails loudly instead of
# silently degrading to claude_cli.
LLM_BACKENDS = ("ollama", "anthropic", "openai", "claude_cli")

# The abstract model names (sonnet/opus/haiku) mean nothing to Ollama; it serves
# real tags. When OLLAMA_MODEL/OPENAI_MODEL are unset, fall back to this tag.
DEFAULT_OLLAMA_CHAT_MODEL = "qwen3.6:35b"


def _clean_env() -> dict:
    """Return os.environ without CLAUDECODE (prevents nested Claude Code)."""
    return {k: v for k, v in os.environ.items() if k != "CLAUDECODE"}


def _openai_client():
    """Build an OpenAI SDK client for the ``openai`` backend.

    The SDK reads ``OPENAI_BASE_URL`` from the env automatically, so pointing this
    at a local vLLM / Ollama ``/v1`` endpoint needs no extra wiring — that's how the
    summarize tool talks to a local LLM. For keyless local servers the key defaults
    to ``"EMPTY"`` whenever a base URL is set.
    """
    try:
        import openai
    except ImportError:
        raise RuntimeError("请安装 openai: pip install openai")
    base_url = os.environ.get("OPENAI_BASE_URL")
    api_key = os.environ.get("OPENAI_API_KEY") or ("EMPTY" if base_url else None)
    if not api_key:
        raise RuntimeError("请设置环境变量 OPENAI_API_KEY（本地服务改设 OPENAI_BASE_URL 即可）")
    return openai.OpenAI(api_key=api_key)


def _openai_model(default: str) -> str:
    """Resolve the served model name: OPENAI_MODEL env wins (local servers serve
    under their own id, e.g. ``qwen3.6:35b``), else the caller's default."""
    return os.environ.get("OPENAI_MODEL") or default


def _openai_extra_body() -> Optional[dict]:
    """Extra request-body params for local reasoning models.

    Set ``OPENAI_REASONING_EFFORT=none`` to switch off a reasoning model's
    ``<think>`` phase (e.g. Qwen3.6 served by Ollama/vLLM) so it emits the answer
    directly instead of burning the token budget thinking. Unset → no effect, so
    real OpenAI calls are untouched.
    """
    effort = os.environ.get("OPENAI_REASONING_EFFORT")
    return {"reasoning_effort": effort} if effort else None


def _ollama_client():
    """OpenAI SDK client pinned at a local Ollama server (keyless).

    Base URL: ``OLLAMA_BASE_URL`` > ``OPENAI_BASE_URL`` > ``127.0.0.1:11434/v1``.
    """
    try:
        import openai
    except ImportError:
        raise RuntimeError("请安装 openai: pip install openai")
    base_url = (os.environ.get("OLLAMA_BASE_URL")
                or os.environ.get("OPENAI_BASE_URL")
                or OLLAMA_DEFAULT_BASE_URL)
    return openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY") or "EMPTY",
                         base_url=base_url)


def _ollama_model(default: str) -> str:
    """Served model name for Ollama: ``OLLAMA_MODEL`` > ``OPENAI_MODEL`` >
    ``DEFAULT_OLLAMA_CHAT_MODEL``. The caller's abstract *default* (sonnet/opus/haiku)
    is not a valid Ollama tag, so it's ignored in favor of a real one."""
    return (os.environ.get("OLLAMA_MODEL")
            or os.environ.get("OPENAI_MODEL")
            or DEFAULT_OLLAMA_CHAT_MODEL)


def _log_chat_done(model: str, t0: float, response) -> None:
    """One observability line per chat call: wall time + token counts.

    Note: Ollama's OpenAI-compat usage hides reasoning tokens (completion_tokens
    counts the answer only, though the time was still spent) — use the native
    API counters for exact accounting.
    """
    usage = getattr(response, "usage", None)
    logger.info(
        "LLM call done (%s): %.1fs, prompt=%s completion=%s tokens",
        model, time.monotonic() - t0,
        getattr(usage, "prompt_tokens", "?"), getattr(usage, "completion_tokens", "?"))


def _chat_raw(client, model: str, prompt: str, timeout: int, max_tokens: int) -> str:
    """Shared OpenAI-compatible chat call returning raw text."""
    logger.info("Calling OpenAI-compatible API (%s), prompt length: %d", model, len(prompt))
    t0 = time.monotonic()
    try:
        response = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            timeout=timeout,
            extra_body=_openai_extra_body(),
        )
        _log_chat_done(model, t0, response)
        return response.choices[0].message.content.strip()
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"OpenAI-compatible API call failed: {e}") from e


def _chat_json(client, model: str, config: "LLMCallConfig") -> dict:
    """Shared OpenAI-compatible chat call returning parsed JSON."""
    logger.info("Calling OpenAI-compatible API (%s, timeout=%ds)...", model, config.timeout)
    t0 = time.monotonic()
    response = client.chat.completions.create(
        model=model,
        max_tokens=config.max_tokens,
        messages=[{"role": "user", "content": config.prompt}],
        response_format={"type": "json_object"},
        timeout=config.timeout,
        extra_body=_openai_extra_body(),
    )
    _log_chat_done(model, t0, response)
    text = response.choices[0].message.content
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return parse_json_response(text)


# ─── Low-level: raw text call ─────────────────────────────────────────

def call_llm_raw(
    prompt: str,
    backend: str = DEFAULT_BACKEND,
    model: str = "sonnet",
    timeout: int = 300,
    max_tokens: int = 8192,
) -> str:
    """Call an LLM and return the raw response text.

    Raises ``RuntimeError`` on failure (missing SDK, bad API key, non-zero exit, etc.).
    """
    logger.debug("LLM raw call: backend=%s model=%s prompt_chars=%d", backend, model, len(prompt))
    if backend == "anthropic":
        return _raw_anthropic(prompt, model, timeout, max_tokens)
    elif backend == "openai":
        return _raw_openai(prompt, model, timeout, max_tokens)
    elif backend == "ollama":
        return _raw_ollama(prompt, model, timeout, max_tokens)
    elif backend == "claude_cli":
        return _raw_claude_cli(prompt, model, timeout)
    raise ValueError(f"Unknown LLM backend {backend!r}; valid: {LLM_BACKENDS}")


def _raw_claude_cli(prompt: str, model: str, timeout: int) -> str:
    logger.info("Calling Claude CLI (%s), prompt length: %d", model, len(prompt))
    try:
        result = subprocess.run(
            ["claude", "--print", "--model", model],
            input=prompt,
            capture_output=True, text=True, timeout=timeout,
            env=_clean_env(),
        )
    except FileNotFoundError:
        raise RuntimeError(
            "Claude CLI not found. Install: npm install -g @anthropic-ai/claude-code")
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Claude CLI timed out after {timeout}s") from e
    if result.returncode != 0:
        raise RuntimeError(
            f"Claude CLI failed (exit {result.returncode}): {result.stderr[:500]}")
    response = result.stdout.strip()
    if not response:
        raise RuntimeError("Claude CLI returned empty response")
    return response


def _raw_anthropic(prompt: str, model: str, timeout: int, max_tokens: int) -> str:
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("请安装 anthropic: pip install anthropic")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("请设置环境变量 ANTHROPIC_API_KEY")

    full_model = ANTHROPIC_MODELS.get(model, model)
    logger.info("Calling Anthropic API (%s), prompt length: %d", full_model, len(prompt))
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=full_model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
            timeout=timeout,
        )
        return response.content[0].text.strip()
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f"Anthropic API call failed: {e}") from e


def _raw_openai(prompt: str, model: str, timeout: int, max_tokens: int) -> str:
    return _chat_raw(_openai_client(), _openai_model(OPENAI_MODELS.get(model, model)),
                     prompt, timeout, max_tokens)


def _raw_ollama(prompt: str, model: str, timeout: int, max_tokens: int) -> str:
    return _chat_raw(_ollama_client(), _ollama_model(model), prompt, timeout, max_tokens)


# ─── High-level: structured JSON calls ────────────────────────────────

@dataclass
class LLMCallConfig:
    """Configuration for a single structured LLM call."""
    prompt: str
    timeout: int = 600
    max_tokens: int = 8192
    # Anthropic tool use (optional)
    anthropic_tools: Optional[list[dict]] = None
    anthropic_tool_name: Optional[str] = None
    # Model overrides
    anthropic_model: str = "claude-sonnet-5"
    openai_model: str = "gpt-4o"
    claude_cli_model: str = "sonnet"
    thinking: Optional[dict] = None


def call_anthropic(config: LLMCallConfig) -> dict:
    """Call Anthropic Claude API and return parsed JSON dict."""
    try:
        import anthropic
    except ImportError:
        raise RuntimeError("请安装 anthropic: pip install anthropic")

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("请设置环境变量 ANTHROPIC_API_KEY")

    client = anthropic.Anthropic(api_key=api_key)

    kwargs = {
        "model": config.anthropic_model,
        "max_tokens": config.max_tokens,
        "messages": [{"role": "user", "content": config.prompt}],
        "timeout": config.timeout,
    }
    if config.thinking:
        kwargs["thinking"] = config.thinking
    if config.anthropic_tools:
        kwargs["tools"] = config.anthropic_tools
        if config.anthropic_tool_name:
            kwargs["tool_choice"] = {"type": "tool", "name": config.anthropic_tool_name}

    logger.info("Calling Anthropic API (timeout=%ds)...", config.timeout)
    response = client.messages.create(**kwargs)

    # Extract from tool_use block first
    for block in response.content:
        if block.type == "tool_use":
            return block.input

    text = response.content[0].text
    return parse_json_response(text)


def call_openai(config: LLMCallConfig) -> dict:
    """Call an OpenAI-compatible API and return parsed JSON dict.

    Real OpenAI, or an explicit ``OPENAI_BASE_URL`` override. For local Ollama use
    the ``ollama`` backend instead — it defaults to localhost and needs no key.
    """
    return _chat_json(_openai_client(), _openai_model(config.openai_model), config)


def call_ollama(config: LLMCallConfig) -> dict:
    """Call a local Ollama server (OpenAI protocol) and return parsed JSON dict."""
    return _chat_json(_ollama_client(), _ollama_model(config.openai_model), config)


def call_claude_cli(config: LLMCallConfig) -> dict:
    """Call Claude Code CLI and return parsed JSON dict."""
    logger.info("Calling Claude Code CLI (timeout=%ds)...", config.timeout)
    cmd = ["claude", "--print", "--model", config.claude_cli_model]
    if config.thinking:
        cmd += ["--effort", "low"]
    try:
        result = subprocess.run(
            cmd,
            input=config.prompt,
            capture_output=True, text=True, timeout=config.timeout,
            env=_clean_env(),
        )
    except FileNotFoundError:
        raise RuntimeError(
            "Claude CLI not found. Install: npm install -g @anthropic-ai/claude-code")
    except subprocess.TimeoutExpired:
        raise  # let caller handle

    if result.returncode != 0:
        raise RuntimeError(
            f"Claude CLI failed (exit {result.returncode}): "
            f"{result.stderr[:500] if result.stderr else ''}")

    text = result.stdout.strip()
    if not text:
        raise RuntimeError("Claude CLI returned empty response")

    return parse_json_response(text)


def call_llm(api: str, config: LLMCallConfig) -> dict:
    """Dispatch to the appropriate backend."""
    logger.debug("LLM call: backend=%s model=%s", api, getattr(config, "model", "?"))
    if api == "anthropic":
        return call_anthropic(config)
    elif api == "openai":
        return call_openai(config)
    elif api == "ollama":
        return call_ollama(config)
    elif api == "claude_cli":
        return call_claude_cli(config)
    raise ValueError(f"Unknown LLM backend {api!r}; valid: {LLM_BACKENDS}")


# ─── Chunking & timeout ──────────────────────────────────────────────

class ChunkTimeoutError(Exception):
    """A single 150K chunk LLM call timed out."""
    def __init__(self, chunk_index: int, total_chunks: int, timeout: int):
        self.chunk_index = chunk_index
        self.total_chunks = total_chunks
        self.timeout = timeout
        if chunk_index < 0:
            msg = f"Merge phase timed out ({timeout}s), increase --timeout"
        else:
            msg = (f"Chunk {chunk_index}/{total_chunks} timed out ({timeout}s), "
                   f"increase --timeout")
        super().__init__(msg)


def chunk_text(texts: list[str], max_chars: int = 150000) -> list[list[str]]:
    """Split a list of texts into groups that fit within *max_chars*."""
    chunks, current, size = [], [], 0
    for t in texts:
        if size + len(t) > max_chars and current:
            chunks.append(current)
            current, size = [], 0
        current.append(t)
        size += len(t)
    if current:
        chunks.append(current)
    return chunks


def timed_llm_call(api: str, config: LLMCallConfig,
                   chunk_idx: int, total: int) -> dict:
    """Single LLM call with timeout detection; raises ChunkTimeoutError."""
    t0 = time.monotonic()
    try:
        result = call_llm(api, config)
    except (subprocess.TimeoutExpired, Exception) as e:
        elapsed = time.monotonic() - t0
        if elapsed >= config.timeout * 0.9:
            raise ChunkTimeoutError(chunk_idx, total, config.timeout) from e
        raise
    elapsed = time.monotonic() - t0
    logger.info("Chunk %d/%d done (%.0fs / %ds)", chunk_idx, total,
                elapsed, config.timeout)

    result = try_repair_result(result, api, config.timeout)
    return result


# ─── Chunk cache ──────────────────────────────────────────────────────

def load_chunk_cache(cache_dir: Path, chunk_hash: str,
                     global_hash: str, total_chunks: int) -> Optional[dict]:
    """Load a cached chunk summary. Returns None on miss."""
    cache_file = cache_dir / f"{chunk_hash}.json"
    if not cache_file.exists():
        return None
    try:
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    meta = data.pop("_chunk_meta", None)
    if not meta:
        return None
    if meta.get("global_hash") != global_hash or meta.get("total_chunks") != total_chunks:
        return None
    if data.get("parse_error"):  # poisoned entry from a failed parse — force re-call
        return None
    logger.info("Chunk cache hit: %s", chunk_hash)
    return data


def save_chunk_cache(cache_dir: Path, chunk_hash: str, result: dict,
                     global_hash: str, total_chunks: int) -> None:
    """Save a chunk summary to disk cache."""
    if result.get("parse_error"):
        logger.warning("Not caching chunk with parse_error")
        return
    data = {**result, "_chunk_meta": {"global_hash": global_hash,
                                       "total_chunks": total_chunks}}
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        atomic_write(cache_dir / f"{chunk_hash}.json",
                     json.dumps(data, ensure_ascii=False, indent=2))
    except OSError as e:
        logger.warning("Chunk cache write failed: %s", e)


def cleanup_chunk_cache(cache_dir: Path) -> None:
    """Delete the chunk cache directory."""
    if cache_dir.exists():
        shutil.rmtree(cache_dir, ignore_errors=True)


# ─── Hierarchical merge ──────────────────────────────────────────────

def hierarchical_merge(api: str, summaries: list[dict],
                       merge_prompt: str,
                       make_config: Callable[[str], LLMCallConfig],
                       timeout: int = 600) -> dict:
    """Recursively merge chunk summaries until everything fits in one call.

    Args:
        api: Backend name ("anthropic" / "openai" / "claude_cli").
        summaries: Per-chunk JSON summary dicts.
        merge_prompt: System/user prompt prefix for the merge phase.
        make_config: Factory — given full prompt text, returns LLMCallConfig.
        timeout: Per-chunk base timeout (merge phase uses 3x).
    """
    valid = [s for s in summaries
             if not (isinstance(s, dict) and s.get("parse_error"))]
    if len(valid) < len(summaries):
        logger.warning("Dropping %d/%d chunk summaries that failed JSON parsing "
                       "from merge", len(summaries) - len(valid), len(summaries))
    if not valid:
        raise ValueError("All chunk summaries failed JSON parsing — nothing to merge")
    summaries = valid

    summary_texts = []
    for i, s in enumerate(summaries):
        text = f"\n--- 第 {i+1} 段总结 ---\n"
        text += json.dumps(s, ensure_ascii=False, indent=2) + "\n"
        summary_texts.append(text)

    combined = "".join(summary_texts)
    merge_overhead = len(merge_prompt) + 200
    merge_timeout = int(timeout * 3)

    if len(combined) + merge_overhead <= 150000:
        logger.info("Merging %d summaries (%s chars, timeout=%ds)...",
                     len(summaries), f"{len(combined):,}", merge_timeout)
        full_prompt = merge_prompt + combined
        config = make_config(full_prompt)
        config.timeout = merge_timeout
        t0 = time.monotonic()
        try:
            result = call_llm(api, config)
        except (subprocess.TimeoutExpired, Exception) as e:
            elapsed = time.monotonic() - t0
            if elapsed >= merge_timeout * 0.9:
                raise ChunkTimeoutError(-1, 0, merge_timeout) from e
            raise
        return try_repair_result(result, api, merge_timeout)

    # Still too large — split and recurse
    text_chunks = chunk_text(summary_texts, max_chars=150000 - merge_overhead)
    n = len(text_chunks)
    logger.info("Merge content too long (%s chars), splitting into %d groups...",
                f"{len(combined):,}", n)

    merged_results = []
    for i, group in enumerate(text_chunks):
        logger.info("Recursive merge group %d/%d...", i + 1, n)
        group_text = merge_prompt + "".join(group)
        config = make_config(group_text)
        config.timeout = merge_timeout
        t0 = time.monotonic()
        try:
            result = call_llm(api, config)
        except (subprocess.TimeoutExpired, Exception) as e:
            elapsed = time.monotonic() - t0
            if elapsed >= merge_timeout * 0.9:
                raise ChunkTimeoutError(-1, 0, merge_timeout) from e
            raise
        result = try_repair_result(result, api, merge_timeout)
        merged_results.append(result)

    return hierarchical_merge(api, merged_results, merge_prompt, make_config, timeout)
