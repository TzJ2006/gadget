"""Hugo frontmatter field translation, language gating, and Qwen review."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import TYPE_CHECKING

from common.engine import _ollama_native_host, _ollama_tags
from common.translation.protect import (
    _reattach_body,
    build_translation_prompt,
    detect_language,
    protect_fragments,
    restore_fragments,
    split_frontmatter,
)

if TYPE_CHECKING:
    from common.engine import TranslationEngine

logger = logging.getLogger(__name__)

# Prose fields — always translated, both directions.
_TRANSLATABLE_KEYS = ("summary:", "description:")

# Label fields: the page title and the tag chips Hugo renders under a post. Also
# reader-facing, so leaving them untranslated puts Chinese on the English page
# just as visibly as an untranslated body — but they are only translated INTO
# English (see the include_labels callers). Labels are a shared taxonomy the
# Chinese pages already carry in English ("Bug Journal", "LeetCode", "python");
# rendering each into Chinese per-page would splinter one label into several
# near-synonyms and break the series/taxonomy pages.
_LABEL_KEYS = ("title:",)
_LABEL_LIST_KEYS = ("keywords:", "tags:", "categories:")

# Local Qwen review of translated frontmatter. Override via
# GADGET_TRANSLATION_REVIEW_MODEL or config.json ``translation.review_model``.
# Disable with GADGET_TRANSLATION_REVIEW=0 or ``translation.review: false``.
DEFAULT_REVIEW_MODEL = "qwen3.6"
_REVIEW_MODEL_ENV = "GADGET_TRANSLATION_REVIEW_MODEL"
_REVIEW_ENABLE_ENV = "GADGET_TRANSLATION_REVIEW"
_FALSEY = ("0", "false", "no", "off")
_TRUTHY = ("1", "true", "yes", "on")


def _split_field(line: str, prefix: str) -> tuple[str, str]:
    """Return (quote_char, unquoted_value) for the part of *line* after *prefix*."""
    raw_value = line[len(prefix):].strip()
    if raw_value[:1] in {'"', "'"} and raw_value[-1:] == raw_value[:1]:
        return raw_value[:1], raw_value[1:-1]
    return "", raw_value


def _scan_frontmatter_fields(
    frontmatter: str,
    predicate: Callable[[str], bool] = lambda _: True,
    include_labels: bool = False,
) -> tuple[list[str], list[tuple[int, str, str, str]]]:
    """Scan YAML frontmatter for translatable fields.

    Covers the prose keys (summary/description) and, with *include_labels*, the
    label fields too (title, and the items of keywords/tags/categories).

    Returns (lines, fields) where each field is
    (line_idx, prefix, quote_char, protected_value).
    *predicate* receives the unquoted raw value and decides inclusion.
    """
    lines = frontmatter.splitlines()
    fields: list[tuple[int, str, str, str]] = []
    keys = _TRANSLATABLE_KEYS + (_LABEL_KEYS if include_labels else ())
    in_list = False

    def take(line_idx: int, prefix: str) -> None:
        quote, raw_value = _split_field(lines[line_idx], prefix)
        if raw_value.strip() and predicate(raw_value):
            protected_value, _ = protect_fragments(raw_value)
            fields.append((line_idx, prefix, quote, protected_value))

    for line_idx, line in enumerate(lines):
        stripped = line.strip()
        if in_list and stripped.startswith("- "):
            take(line_idx, line[: line.index("- ") + 1])
            continue
        in_list = include_labels and stripped in _LABEL_LIST_KEYS
        for key in keys:
            if stripped.startswith(key):
                take(line_idx, line[: line.index(key) + len(key)])
                break
    return lines, fields


def _apply_translated_fields(
    lines: list[str],
    fields: list[tuple[int, str, str, str]],
    results: list[str],
) -> list[str]:
    """Apply batch-translated results back into frontmatter lines."""
    result_lines = list(lines)
    for (line_idx, prefix, quote, _), translated in zip(fields, results, strict=True):
        _, raw_value = _split_field(lines[line_idx], prefix)
        _, protected_map = protect_fragments(raw_value)
        restored = restore_fragments(translated, protected_map).strip().strip('"').strip("'")
        result_lines[line_idx] = f"{prefix} {quote}{restored}{quote}".rstrip()
    return result_lines


def frontmatter_language_mismatches(
    frontmatter: str, expected_lang: str,
) -> list[tuple[int, str, str, str]]:
    """Fields whose detected language does not match *expected_lang*.

    English pages check title/tags as well as summary/description (a Chinese
    title on an otherwise-English body used to slip past document-level 5% CJK).
    Chinese pages do not judge title/tags: originally-English labels stay English.
    """
    if not frontmatter:
        return []
    _, fields = _scan_frontmatter_fields(
        frontmatter,
        predicate=lambda v: detect_language(v) != expected_lang,
        include_labels=expected_lang == "en",
    )
    return fields


def _restore_field_value(
    lines: list[str], field: tuple[int, str, str, str], translated: str,
) -> tuple[str, str]:
    """Return (original_raw, restored_translation) for one scanned field."""
    line_idx, prefix, _, _ = field
    _, raw_value = _split_field(lines[line_idx], prefix)
    _, protected_map = protect_fragments(raw_value)
    restored = restore_fragments(translated, protected_map).strip().strip('"').strip("'")
    return raw_value, restored


def _gate_english(value: str, original: str, line_idx: int) -> str:
    """Keep *original* when an English-target field is still Chinese."""
    if detect_language(value) == "en":
        return value
    logger.warning(
        "Frontmatter field at line %d still wrong language after translation/review, "
        "keeping original",
        line_idx,
    )
    return original


def _finalize_translated_fields(
    lines: list[str],
    fields: list[tuple[int, str, str, str]],
    results: list[str],
    target_lang: str,
) -> list[str]:
    """Restore HY-MT results, run Qwen review, language-gate English fields."""
    originals: list[str] = []
    drafts: list[str] = []
    prefixes: list[str] = []
    for field, translated in zip(fields, results, strict=True):
        original, restored = _restore_field_value(lines, field, translated)
        originals.append(original)
        drafts.append(restored)
        prefixes.append(field[1])

    reviewed = review_frontmatter_fields(
        originals, drafts, target_lang, prefixes=prefixes,
    )
    if target_lang == "en":
        reviewed = [
            _gate_english(value, original, field[0])
            for field, original, value in zip(fields, originals, reviewed, strict=True)
        ]
    return _apply_translated_fields(lines, fields, reviewed)


def sanitize_frontmatter_language(
    content: str,
    expected_lang: str,
    engine: TranslationEngine,
) -> str:
    """Fix reader-facing frontmatter fields that are in the wrong language.

    Scans the translatable scalar and list fields. If any field's detected
    language doesn't match *expected_lang*, translates it via *engine*.
    Returns the full document with corrected frontmatter (body unchanged).
    """
    frontmatter, body = split_frontmatter(content)
    if not frontmatter:
        return content

    lines, fixups = _scan_frontmatter_fields(
        frontmatter, predicate=lambda v: detect_language(v) != expected_lang,
        include_labels=expected_lang == "en",
    )

    if not fixups:
        return content

    prompts = [
        build_translation_prompt(f[3], expected_lang, markdown=False)
        for f in fixups
    ]
    results = engine.generate_batch(prompts, max_new_tokens=512)
    lines = _finalize_translated_fields(lines, fixups, results, expected_lang)
    return _reattach_body(frontmatter, "\n".join(lines), body)


def translate_frontmatter(
    frontmatter: str,
    target_lang: str,
    engine: TranslationEngine,
) -> str:
    """Translate the reader-facing YAML frontmatter fields.

    Prose keys are ``_TRANSLATABLE_KEYS`` (summary/description). Label keys
    (``_LABEL_KEYS`` / ``_LABEL_LIST_KEYS``: title, keywords, tags, categories)
    are translated only into English so Chinese pages keep a shared English
    taxonomy. After HY-MT, a local Qwen review may correct leftover errors;
    English-target fields that are still Chinese are left as the original.
    """
    if not frontmatter:
        return ""

    lines, fields = _scan_frontmatter_fields(
        frontmatter, include_labels=target_lang == "en")
    if not fields:
        return frontmatter

    prompts = [
        build_translation_prompt(f[3], target_lang, markdown=False)
        for f in fields
    ]
    results = engine.generate_batch(prompts, max_new_tokens=512)
    result_lines = _finalize_translated_fields(lines, fields, results, target_lang)
    return "\n".join(result_lines)


# ---------------------------------------------------------------------------
# Local Qwen review
# ---------------------------------------------------------------------------

def resolve_review_model() -> str:
    """``GADGET_TRANSLATION_REVIEW_MODEL`` > config ``translation.review_model`` > default."""
    env = os.environ.get(_REVIEW_MODEL_ENV, "").strip()
    if env:
        return env
    from common.config import load_section
    cfg = load_section("translation")
    configured = cfg.get("review_model")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    return DEFAULT_REVIEW_MODEL


def review_is_enabled() -> bool:
    """False when explicitly disabled via env or ``translation.review``."""
    flag = os.environ.get(_REVIEW_ENABLE_ENV, "").strip().lower()
    if flag in _FALSEY:
        return False
    if flag in _TRUTHY:
        return True
    from common.config import load_section
    cfg = load_section("translation")
    if "review" in cfg:
        val = cfg["review"]
        if isinstance(val, bool):
            return val
        if isinstance(val, (int, float)):
            return bool(val)
        if isinstance(val, str) and val.strip().lower() in _FALSEY:
            return False
    return True


def _match_review_tag(requested: str, tags: list[str]) -> str | None:
    """Resolve *requested* against pulled Ollama tags (bare name matches ``:tag``)."""
    if requested in tags:
        return requested
    base = requested.split(":")[0]
    matches = [t for t in tags if t.split(":")[0] == base]
    if not matches:
        return None
    for t in matches:
        if t == base or t.endswith(":latest"):
            return t
    return matches[0]


def resolve_review_tag() -> str | None:
    """Pulled Ollama tag for frontmatter review, or None to skip.

    Skip (with a warning) when review is disabled, Ollama is unreachable, or
    the configured model is not pulled.
    """
    if not review_is_enabled():
        logger.info("Frontmatter review skipped: disabled by config/env")
        return None
    requested = resolve_review_model()
    tags = _ollama_tags(_ollama_native_host())
    if tags is None:
        logger.warning(
            "Frontmatter review skipped: Ollama not reachable (wanted %s)",
            requested,
        )
        return None
    resolved = _match_review_tag(requested, tags)
    if resolved is None:
        logger.warning(
            "Frontmatter review skipped: model %s is not pulled (available: %s)",
            requested, ", ".join(tags) or "none",
        )
        return None
    return resolved


def _call_review_llm(prompt: str, model: str) -> str:
    """Call local Qwen via ``common.llm``. Pins ``OLLAMA_MODEL`` because the
    ollama backend otherwise ignores the per-call model argument.
    """
    from common.llm import call_llm_raw
    prev = os.environ.get("OLLAMA_MODEL")
    os.environ["OLLAMA_MODEL"] = model
    try:
        return call_llm_raw(
            prompt, backend="ollama", model=model, timeout=60, max_tokens=1024,
        )
    finally:
        if prev is None:
            os.environ.pop("OLLAMA_MODEL", None)
        else:
            os.environ["OLLAMA_MODEL"] = prev


def _build_review_prompt(
    originals: list[str],
    drafts: list[str],
    target_lang: str,
    prefixes: list[str],
) -> str:
    target_name = "中文" if target_lang == "zh" else "English"
    items = []
    for i, (prefix, original, draft) in enumerate(
        zip(prefixes, originals, drafts, strict=True)
    ):
        key = prefix.strip().rstrip(":") or "item"
        items.append(
            f"{i}. [{key}]\n   原文: {original}\n   初译: {draft}"
        )
    return (
        f"你是双语网站 YAML frontmatter 审校。目标语言：{target_name}。\n"
        "规则：\n"
        "1. 该翻译的要翻译（说明性标题、标签、摘要必须译成目标语言）。\n"
        "2. 专业名词、项目名、工具名、模型名、缩写保留原文"
        "（例如 LeRobot, NeurIPS, MIHD, RecoverBench, BlackHole, STAIG, Hugo, Claude）。\n"
        "3. 标题或专业名词原本就是英文的，在中文界面保留英文，不要强行意译。\n"
        "只输出 JSON："
        '{"fields": [{"index": 0, "value": "审校后的值"}, ...]}。\n'
        "只列出需要改动的字段；初译已合格则返回 {\"fields\": []}。\n\n"
        + "\n".join(items)
    )


def review_frontmatter_fields(
    originals: list[str],
    drafts: list[str],
    target_lang: str,
    *,
    prefixes: list[str] | None = None,
) -> list[str]:
    """Review HY-MT drafts with local Qwen. Returns a list the same length as *drafts*.

    Identity (the drafts unchanged) when review is gated off or the call fails.
    """
    if not originals:
        return list(drafts)
    tag = resolve_review_tag()
    if not tag:
        return list(drafts)
    keys = prefixes if prefixes is not None else [""] * len(originals)
    prompt = _build_review_prompt(originals, drafts, target_lang, keys)
    logger.info("Reviewing %d frontmatter field(s) with %s", len(originals), tag)
    try:
        raw = _call_review_llm(prompt, tag)
    except Exception as exc:
        logger.warning("Frontmatter review skipped: %s call failed: %s", tag, exc)
        return list(drafts)
    from common.json_utils import try_parse_json
    parsed = try_parse_json(raw)
    if not isinstance(parsed, dict):
        logger.warning("Frontmatter review skipped: %s returned non-JSON", tag)
        return list(drafts)
    updates = parsed.get("fields")
    if not isinstance(updates, list):
        return list(drafts)
    out = list(drafts)
    for item in updates:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item["index"])
        except (KeyError, TypeError, ValueError):
            continue
        value = item.get("value")
        if not isinstance(value, str) or not value.strip():
            continue
        if 0 <= idx < len(out):
            out[idx] = value.strip().strip('"').strip("'")
    return out
