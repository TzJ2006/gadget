"""JSON parsing and repair utilities for LLM responses."""

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ─── Non-LLM parsing stages ──────────────────────────────────────────

def _fix_unescaped_quotes(text: str) -> str:
    """Fix unescaped double quotes inside JSON string values."""
    result = []
    i = 0
    n = len(text)
    in_string = False

    while i < n:
        ch = text[i]

        if not in_string:
            result.append(ch)
            if ch == '"':
                in_string = True
            i += 1
        else:
            if ch == '\\':
                result.append(ch)
                if i + 1 < n:
                    result.append(text[i + 1])
                    i += 2
                else:
                    i += 1
            elif ch == '"':
                j = i + 1
                while j < n and text[j] in ' \t\r\n':
                    j += 1
                if j >= n or text[j] in ',:]}\n':
                    result.append(ch)
                    in_string = False
                else:
                    result.append('\\')
                    result.append('"')
                i += 1
            else:
                result.append(ch)
                i += 1

    return ''.join(result)


def try_parse_json(text: str) -> Optional[dict]:
    """Try to parse JSON using non-LLM strategies (stages 1-3).

    Returns parsed dict on success, None on failure.
    Uses depth-based brace matching (more robust than rfind).
    """
    text = text.strip()

    # Stage 1: direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Stage 2: extract from markdown code block (prefer largest valid block)
    blocks = re.findall(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
    if blocks:
        parsed_blocks = []
        for block in blocks:
            try:
                parsed_blocks.append(json.loads(block.strip()))
            except json.JSONDecodeError:
                continue
        if parsed_blocks:
            return max(parsed_blocks, key=lambda d: len(json.dumps(d)))

    # Stage 3: find a valid { ... } object via depth-based brace matching.
    # If the first balanced region doesn't parse (e.g. a stray "{the}" in prose
    # before the real JSON), keep scanning from the next '{' instead of giving up.
    brace_start = text.find('{')
    while brace_start >= 0:
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[brace_start:i + 1])
                    except json.JSONDecodeError:
                        break  # invalid region — fall through to the next '{'
        brace_start = text.find('{', brace_start + 1)

    return None


def parse_json_response(text: str, error_log_dir: Optional[Path] = None) -> dict:
    """Extract and parse JSON from an LLM response.

    Stages: direct parse → code block → depth brace match → fix unescaped quotes.
    On failure returns ``{"raw_response": text, "parse_error": "..."}``.
    """
    text = text.strip()

    # Stages 1-3
    result = try_parse_json(text)
    if result is not None:
        return result

    # Stage 4: fix unescaped quotes inside the outermost { ... }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        candidate = text[start:end + 1]
        repaired = _fix_unescaped_quotes(candidate)
        if repaired != candidate:
            try:
                return json.loads(repaired)
            except json.JSONDecodeError:
                pass

    logger.warning("JSON parse failed — cannot extract valid JSON from LLM response")

    # Optional error log
    if error_log_dir:
        try:
            from common.io import atomic_write
            errors_dir = error_log_dir / "errors"
            ts = datetime.now().strftime("%Y%m%dT%H%M%S")
            error_file = errors_dir / f"parse_fail_{ts}.txt"
            content = (f"[{datetime.now().isoformat()}] JSON parse failed\n"
                       f"--- raw response ({len(text)} chars) ---\n"
                       f"{text}\n")
            atomic_write(error_file, content)
            logger.info("Raw response saved to %s", error_file)
        except Exception as e:
            logger.warning("Failed to save error log: %s", e)

    return {"raw_response": text, "parse_error": "Cannot extract JSON"}


# ─── LLM-based repair ────────────────────────────────────────────────

_JSON_REPAIR_PROMPT = """以下文本应该是一个 JSON 对象但解析失败了。
请提取或修复其中的 JSON，只返回有效的 JSON 对象，不要添加任何其他文字。

原始文本：
"""


def repair_json_with_llm(
    raw_text: str,
    backend: str,
    timeout: int = 120,
    strategy: str = "single",
    max_chars: int = 5000,
) -> Optional[dict]:
    """Attempt to repair broken JSON using a lightweight LLM call.

    Strategies:
        "single"     — haiku only (fast, default)
        "escalating" — haiku → sonnet → opus (thorough)

    ``max_chars`` caps the payload sent to the repair LLM (larger keeps more of a
    long response at the cost of a bigger prompt). Returns parsed dict on success,
    None on failure.
    """
    # Lazy import to avoid circular dependency (json_utils ↔ llm)
    from common.llm import call_llm_raw

    models = ["haiku"] if strategy == "single" else ["haiku", "sonnet", "opus"]
    if len(raw_text) > max_chars:
        logger.warning("JSON repair payload truncated %d -> %d chars; tail dropped",
                       len(raw_text), max_chars)
    prompt = _JSON_REPAIR_PROMPT + raw_text[:max_chars]

    for model in models:
        try:
            logger.info("Attempting JSON repair with %s...", model)
            response_text = call_llm_raw(
                prompt, backend=backend, model=model, timeout=timeout)
            parsed = try_parse_json(response_text)
            if parsed is not None:
                logger.info("JSON repair with %s succeeded", model)
                return parsed
        except Exception as e:
            logger.warning("JSON repair with %s failed: %s", model, e)
            continue

    return None


def try_repair_result(result: dict, backend: str, timeout: int) -> dict:
    """If *result* contains a parse_error, attempt LLM repair."""
    if result.get("parse_error") and result.get("raw_response"):
        logger.warning("JSON parse failed, attempting LLM repair...")
        repaired = repair_json_with_llm(
            result["raw_response"], backend, timeout=min(timeout, 120))
        if repaired:
            logger.info("LLM repair succeeded")
            return repaired
        logger.warning("LLM repair also failed, keeping original error response")
    return result
