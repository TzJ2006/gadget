"""Shared markdown translation helpers using local inference (vLLM / transformers).

Provides chunked translation for large documents and fragment protection
to preserve code blocks, URLs, and Hugo shortcodes during translation.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from common.engine import TranslationEngine, create_engine

logger = logging.getLogger(__name__)

LANG_NAMES = {"en": "English", "zh": "Chinese"}

# ---------------------------------------------------------------------------
# Frontmatter splitting
# ---------------------------------------------------------------------------

FRONTMATTER_RE = re.compile(r"^(---\s*\n.*?\n---\s*\n?)(.*)$", re.DOTALL)


def split_frontmatter(text: str) -> tuple[str, str]:
    """Split Hugo markdown into (frontmatter_block, body).

    Returns ("", text) when no frontmatter is found.
    """
    match = FRONTMATTER_RE.match(text)
    if match:
        return match.group(1), match.group(2)
    return "", text


def _reattach_body(frontmatter: str, translated_fm: str, body: str) -> str:
    """Rejoin a re-serialized frontmatter block to its body.

    ``splitlines()`` + ``"\\n".join()`` drops the frontmatter block's trailing
    newline(s), which would glue the closing ``---`` fence onto the first body
    line and corrupt the document. Restore the original block's exact trailing
    newline(s) so the boundary is preserved.
    """
    if not frontmatter:
        return f"{translated_fm}{body}"
    trailing = frontmatter[len(frontmatter.rstrip("\n")):]
    return translated_fm.rstrip("\n") + trailing + body


# ---------------------------------------------------------------------------
# Fragment protection (code blocks, shortcodes, URLs, inline code)
# ---------------------------------------------------------------------------

PROTECTED_PATTERNS = [
    # Embedded usage-card component (summarize reports) — raw HTML, keep verbatim
    re.compile(r"(?s)<style>\s*\.usage-card.*?</style>"),
    re.compile(r'(?s)<footer class="usage-card">.*?</footer>'),
    re.compile(r"(?ms)^```.*?^```[ \t]*\n?"),
    re.compile(r"(?s)\{\{[%<].*?[>%]\}\}"),
    re.compile(r"(?s)<!--.*?-->"),
    re.compile(r"`[^`\n]+`"),
    re.compile(r"https?://[^\s)>\]]+"),
]


def protect_fragments(text: str) -> tuple[str, dict[str, str]]:
    """Replace untranslatable fragments with placeholder tokens."""
    protected: dict[str, str] = {}
    counter = 0

    for pattern in PROTECTED_PATTERNS:
        def replacer(match: re.Match[str]) -> str:
            nonlocal counter
            token = f"[[[HYMTPH_{counter}]]]"
            protected[token] = match.group(0)
            counter += 1
            return token

        text = pattern.sub(replacer, text)

    return text, protected


# The model occasionally mangles a placeholder's surrounding brackets/spacing
# (e.g. emits `[[[HYMTPH_1]]` with one bracket dropped), which a literal replace
# misses and silently drops the protected fragment (URL/code/etc). This tolerant
# matcher mops those up. Anchored on `HYMTPH_\d+` so it cannot match real content.
_PLACEHOLDER_RE = re.compile(r"\[{2,3}\s*(HYMTPH_\d+)\s*\]{2,3}")


def restore_fragments(text: str, protected: dict[str, str]) -> str:
    """Restore placeholder tokens back to original fragments.

    First an exact replace, then a tolerant pass that recovers placeholders the
    model lightly corrupted (wrong bracket count / stray spaces).
    """
    for token, original in protected.items():
        text = text.replace(token, original)

    def _recover(match: re.Match[str]) -> str:
        canonical = f"[[[{match.group(1)}]]]"
        return protected.get(canonical, match.group(0))

    return _PLACEHOLDER_RE.sub(_recover, text)


# ---------------------------------------------------------------------------
# Text chunking for large documents
# ---------------------------------------------------------------------------

_SENTENCE_BREAKS = "。！？；!?;．"


def _hard_split(chunk: str, max_chars: int) -> list[str]:
    """Last-resort split for a boundary-less blob longer than *max_chars*.

    Cuts at the latest sentence-ending punctuation in each window (plain cut when
    none exists), so the translator's num_ctx can never be silently overflowed by
    one giant single-line paragraph. Concatenating the parts reproduces the input
    byte-for-byte.
    """
    parts: list[str] = []
    rest = chunk
    while len(rest) > max_chars:
        window = rest[:max_chars]
        cut = max(window.rfind(p) for p in _SENTENCE_BREAKS) + 1
        if cut <= max_chars // 2:  # no usable sentence break in the window
            cut = max_chars
        parts.append(rest[:cut])
        rest = rest[cut:]
    if rest:
        parts.append(rest)
    return parts


def split_large_text(
    text: str, max_chars: int = 7000, target_chars: int | None = None
) -> list[str]:
    """Split text into chunks at header or blank-line boundaries.

    With *target_chars* set, also packs paragraphs into ~target_chars chunks even
    when the whole text fits under max_chars — so a multi-paragraph page becomes a
    real batch (the GPU is launch-bound at batch=1; batching is the only real
    speedup — see translator/perf_report.md). max_chars is a HARD ceiling: a
    paragraph with no internal boundary is split at sentence punctuation as a
    last resort (silently overflowing the translator's context window truncates
    output, which is strictly worse for meaning than a sentence-boundary cut).
    target_chars=None keeps the original max_chars-only behavior, so other
    callers (website/research/summarize) are unaffected.
    """
    soft = target_chars or max_chars
    if len(text) <= soft:
        return [text]

    lines = text.splitlines(keepends=True)
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    breakpoints: list[int] = []

    def flush(chunk_lines: list[str]) -> None:
        chunk = "".join(chunk_lines)
        if not chunk:
            return
        if len(chunk) > max_chars:
            chunks.extend(_hard_split(chunk, max_chars))
        else:
            chunks.append(chunk)

    for line in lines:
        current.append(line)
        current_len += len(line)
        if line.startswith("#") or not line.strip():
            breakpoints.append(len(current))

        # soft cut: reached target while sitting on a boundary → emit whole buffer
        if current_len >= soft and breakpoints and breakpoints[-1] == len(current):
            flush(current)
            current = []
            current_len = 0
            breakpoints = []
            continue

        if current_len < max_chars:
            continue

        if breakpoints:
            cut = breakpoints[-1]
        else:
            cut = len(current)

        flush(current[:cut])
        current = current[cut:]
        current_len = sum(len(item) for item in current)
        breakpoints = []
        for index, item in enumerate(current, start=1):
            if item.startswith("#") or not item.strip():
                breakpoints.append(index)

    flush(current)
    return [chunk for chunk in chunks if chunk]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_GARBAGE_RE = re.compile(r"^-{3,}(END|BEGIN|结束|开始)?-{0,3}$")


def clean_translated_document(text: str) -> str:
    """Strip wrapper text so the result starts with frontmatter.

    Raises ValueError when the output is clearly garbage (too short,
    marker-only, or missing frontmatter structure).
    """
    result = text.strip()

    if _GARBAGE_RE.match(result):
        raise ValueError(f"Translated output is only a marker: {result!r}")

    if result.startswith("---"):
        _validate_minimum_content(result)
        return result

    idx = result.find("---")
    if idx >= 0:
        result = result[idx:]
        _validate_minimum_content(result)
        return result

    raise ValueError("Translated output is missing frontmatter delimiters")


def _validate_minimum_content(text: str) -> None:
    """Reject outputs that are too short to be a real Hugo document."""
    if len(text) < 50:
        raise ValueError(
            f"Translated output too short ({len(text)} chars): {text[:80]!r}"
        )
    parts = text.split("---")
    if len(parts) < 3:
        raise ValueError("Translated output has unclosed frontmatter")


def validate_translated_output(
    translated: str, original: str, target_lang: str | None = None
) -> str:
    """Clean and validate translated output against the original.

    Raises ValueError if the output is garbage, suspiciously short relative to
    the original, or (when *target_lang* is given) still in the source language.
    """
    cleaned = clean_translated_document(translated)
    min_ratio = 0.15
    if len(cleaned) < len(original) * min_ratio:
        raise ValueError(
            f"Translated output is {len(cleaned)} chars but original is "
            f"{len(original)} chars ({len(cleaned)/len(original):.0%} ratio)"
        )
    if target_lang and wrong_language(cleaned, target_lang):
        raise ValueError(f"Translated output is not in {target_lang}")
    return cleaned


# A model that echoes its input (server hiccup, prompt confusion) used to sail
# through validation and get stamped with the src-hash marker — freezing the
# untranslated original as the "current" translation forever. Judge on prose
# only: code/URLs/HTML are protected fragments, and a code-heavy page is mostly
# non-prose, which would otherwise always read as English.
# Low on purpose: a near-empty daily report's whole prose is a heading or two
# (~35 chars). A false positive only costs a re-translation next run; a false
# negative freezes an untranslated page on the site.
_PROSE_MIN = 20


def wrong_language(text: str, target_lang: str) -> bool:
    """True when *text* has enough prose to judge and it is not in *target_lang*."""
    protected, _ = protect_fragments(text)
    prose = _PLACEHOLDER_RE.sub("", protected).strip()
    return len(prose) >= _PROSE_MIN and detect_language(prose) != target_lang


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

def detect_language(text: str) -> str:
    """Heuristic: if CJK chars exceed 5% of content, treat it as Chinese."""
    stripped = text.strip()
    if not stripped:
        return "en"
    cjk = sum(1 for char in stripped if "\u4e00" <= char <= "\u9fff")
    return "zh" if cjk / len(stripped) > 0.05 else "en"


def chunk_ceiling(text: str) -> int:
    """Hard chunk-size cap (chars) so a chunk + 4096 output tokens fits the
    Ollama translator's num_ctx (default 8192 \u2014 see OllamaEngine).

    CJK runs ~0.65 tokens/char, so a 7000-char zh chunk (~4.5k tokens) would
    overflow and get silently left-truncated; 5000 chars (~3.3k tokens) fits.
    EN text at 7000 chars is only ~1.8k tokens \u2014 the original ceiling stands.
    """
    return 5000 if detect_language(text) == "zh" else 7000


def zh_path(relative_path: Path) -> Path:
    """Convert a .md path to its .zh.md counterpart."""
    return relative_path.parent / f"{relative_path.stem}.zh{relative_path.suffix}"


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------

def build_translation_prompt(
    text: str,
    target_lang: str,
    *,
    markdown: bool = True,
    background_text: str | None = None,
) -> str:
    task = "Markdown文本" if markdown else "文本"
    target_name = "中文" if target_lang == "zh" else "English"
    proper_nouns = (
        "不要翻译专有名词、项目名称、工具名称、模型名称和缩写词，保留原文"
        "（例如 LeRobot, NeurIPS, MIHD, RecoverBench, BlackHole, STAIG, Hugo, Claude 等）。"
    )
    preserve = (
        "保持原始Markdown格式不变；不要翻译代码块、行内代码、URL、文件路径、HTML标签、Hugo shortcodes、占位符 token。"
        if markdown
        else "保留占位符 token、URL、文件路径和代码标识符。"
    )
    instruction = (
        f"将以下{task}翻译为{target_name}，注意只需要输出翻译后的结果，不要额外解释。"
        f"{proper_nouns}{preserve}"
    )
    # background_text gives the model document-level context (terminology /
    # referents) so independently-translated chunks stay consistent. None →
    # byte-identical to the original prompt (other callers unaffected).
    if background_text:
        return (
            f"【背景信息】\n{background_text}\n\n"
            f"{instruction}\n\n"
            f"【待翻译文本】\n{text}"
        )
    return f"{instruction}\n\n{text}"


# ---------------------------------------------------------------------------
# Batch translation pipeline
# ---------------------------------------------------------------------------

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

    accepted_fields: list[tuple[int, str, str, str]] = []
    accepted_results: list[str] = []
    for field, translated in zip(fixups, results, strict=True):
        line_idx = field[0]
        _, raw_value = _split_field(lines[line_idx], field[1])
        _, protected_map = protect_fragments(raw_value)
        restored = restore_fragments(translated, protected_map).strip().strip('"').strip("'")
        if detect_language(restored) == expected_lang:
            accepted_fields.append(field)
            accepted_results.append(translated)
            logger.info("Fixed frontmatter language mismatch on line %d", line_idx)
        else:
            logger.warning(
                "Frontmatter field at line %d still wrong language after fix attempt, keeping original",
                line_idx,
            )

    if accepted_fields:
        lines = _apply_translated_fields(lines, accepted_fields, accepted_results)
    return _reattach_body(frontmatter, "\n".join(lines), body)


def translate_frontmatter(
    frontmatter: str,
    target_lang: str,
    engine: TranslationEngine,
) -> str:
    """Translate the reader-facing YAML frontmatter fields (see
    ``_TRANSLATABLE_KEYS`` / ``_TRANSLATABLE_LIST_KEYS``)."""
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
    result_lines = _apply_translated_fields(lines, fields, results)
    return "\n".join(result_lines)


def translate_body(
    body: str,
    target_lang: str,
    engine: TranslationEngine,
    pbar: Any | None = None,
    target_chars: int | None = None,
    context_chars: int = 0,
) -> str:
    """Translate body text using collect-then-batch pipeline.

    *target_chars* (opt-in) micro-chunks multi-paragraph text into a batch — the
    only real speedup at batch=1 (see translator/perf_report.md).

    *context_chars* (opt-in, >0) injects the document body (capped to this many
    chars) as background into each chunk's prompt, so independently-translated
    chunks keep terminology/referents consistent. Only applied when there is more
    than one chunk; 0 (default) disables it, leaving other callers unaffected.
    """
    protected_body, protected = protect_fragments(body)
    chunks = split_large_text(
        protected_body, max_chars=chunk_ceiling(protected_body), target_chars=target_chars,
    )

    non_empty = [(i, chunk) for i, chunk in enumerate(chunks) if chunk.strip()]
    if not non_empty:
        return restore_fragments("".join(chunks), protected)

    # head-cap the doc as background — ponytail: summary/sliding-window if quality needs it
    background = protected_body[:context_chars] if context_chars and len(non_empty) > 1 else None
    prompts = [
        build_translation_prompt(chunk, target_lang, markdown=True, background_text=background)
        for _, chunk in non_empty
    ]
    logger.info("Translating %d chunks as batch%s", len(prompts), " (with context)" if background else "")

    results = engine.generate_batch(
        prompts,
        max_new_tokens=4096,
    )

    translated_chunks = list(chunks)
    for (i, _), result in zip(non_empty, results, strict=True):
        translated_chunks[i] = result
        if pbar:
            pbar.update(1)

    translated = "".join(translated_chunks)
    return restore_fragments(translated, protected)


def count_translation_chunks(content: str) -> int:
    """Return the number of non-empty chunks a document would be split into.

    Mirrors translate_body exactly (protect first, then ceiling on the protected
    text) — protection can flip the detected language and thus the ceiling.
    """
    _, body = split_frontmatter(content)
    protected, _ = protect_fragments(body)
    chunks = split_large_text(protected, max_chars=chunk_ceiling(protected))
    return sum(1 for c in chunks if c.strip())


def translate_documents_batch(
    documents: list[str],
    source_lang: str,
    target_lang: str,
    engine: TranslationEngine,
    pbar: Any | None = None,
) -> list[str]:
    """Translate multiple Hugo documents in a single cross-document batch.

    Collects all translation prompts (frontmatter fields + body chunks) from
    all documents, sends them as one large batch to the engine, then reassembles
    each document from its slice of results. Much faster on GPU than per-doc calls.

    Returns a list of translated documents (same order as input).
    Raises ValueError for any document that fails validation.
    """
    # Phase 1: Pre-process all documents, collect prompts
    doc_plans: list[dict] = []
    all_prompts: list[str] = []
    all_max_tokens: list[int] = []

    for content in documents:
        frontmatter, body = split_frontmatter(content)

        # Frontmatter fields
        fm_lines, fm_fields = _scan_frontmatter_fields(
            frontmatter, include_labels=target_lang == "en") if frontmatter else ([], [])
        fm_prompt_indices: list[int] = []
        for f in fm_fields:
            fm_prompt_indices.append(len(all_prompts))
            all_prompts.append(build_translation_prompt(f[3], target_lang, markdown=False))
            all_max_tokens.append(512)

        # Body chunks
        protected_body, protected_map = protect_fragments(body)
        chunks = split_large_text(protected_body, max_chars=chunk_ceiling(protected_body))
        non_empty = [(i, chunk) for i, chunk in enumerate(chunks) if chunk.strip()]
        body_prompt_indices: list[int] = []
        for _, chunk in non_empty:
            body_prompt_indices.append(len(all_prompts))
            all_prompts.append(build_translation_prompt(chunk, target_lang, markdown=True))
            all_max_tokens.append(4096)

        doc_plans.append({
            "content": content,
            "frontmatter": frontmatter,
            "body": body,
            "fm_lines": fm_lines,
            "fm_fields": fm_fields,
            "fm_prompt_indices": fm_prompt_indices,
            "chunks": chunks,
            "non_empty": non_empty,
            "protected_map": protected_map,
            "body_prompt_indices": body_prompt_indices,
        })

    if not all_prompts:
        return list(documents)

    # Phase 2: Batch inference with progress
    logger.info("Cross-document batch: %d prompts from %d documents", len(all_prompts), len(documents))

    # Split by max_tokens groups (512 vs 4096) for efficiency
    short_indices = [i for i, t in enumerate(all_max_tokens) if t <= 512]
    long_indices = [i for i, t in enumerate(all_max_tokens) if t > 512]

    all_results: list[str] = [""] * len(all_prompts)

    # Process short prompts (frontmatter fields) — fast, no progress needed
    if short_indices:
        short_prompts = [all_prompts[i] for i in short_indices]
        short_results = engine.generate_batch(short_prompts, max_new_tokens=512)
        for idx, result in zip(short_indices, short_results):
            all_results[idx] = result

    # Process long prompts (body chunks) in sub-batches for progress feedback
    if long_indices:
        sub_batch_size = 48
        for batch_start in range(0, len(long_indices), sub_batch_size):
            batch_idx = long_indices[batch_start:batch_start + sub_batch_size]
            batch_prompts = [all_prompts[i] for i in batch_idx]
            batch_results = engine.generate_batch(batch_prompts, max_new_tokens=4096)
            for idx, result in zip(batch_idx, batch_results):
                all_results[idx] = result
            if pbar:
                pbar.update(len(batch_results))

    # Phase 3: Reassemble documents
    translated_docs: list[str] = []
    for plan in doc_plans:
        # Reassemble frontmatter
        if plan["fm_fields"]:
            fm_results = [all_results[i] for i in plan["fm_prompt_indices"]]
            result_lines = _apply_translated_fields(plan["fm_lines"], plan["fm_fields"], fm_results)
            translated_fm = "\n".join(result_lines)
        else:
            translated_fm = plan["frontmatter"]

        # Reassemble body
        translated_chunks = list(plan["chunks"])
        for (chunk_idx, _), prompt_idx in zip(plan["non_empty"], plan["body_prompt_indices"]):
            translated_chunks[chunk_idx] = all_results[prompt_idx]

        translated_body = "".join(translated_chunks)
        translated_body = restore_fragments(translated_body, plan["protected_map"])

        result = _reattach_body(plan["frontmatter"], translated_fm, translated_body)
        result = validate_translated_output(result, plan["content"], target_lang)
        translated_docs.append(result)

    return translated_docs


def translate_markdown_document(
    content: str,
    source_lang: str,
    target_lang: str,
    *,
    engine: TranslationEngine | None = None,
    model: str | None = None,
    pbar: Any | None = None,
) -> str:
    """Translate a full Hugo markdown document using local inference.

    Uses a collect-then-batch pipeline: frontmatter fields are translated
    as a batch, body chunks are translated as a single batch call.
    Code blocks, URLs, and shortcodes are protected during translation.

    Pass a tqdm-compatible *pbar* to get per-chunk progress updates.
    """
    def _do_translate(eng: TranslationEngine) -> str:
        frontmatter, body = split_frontmatter(content)
        translated_fm = translate_frontmatter(frontmatter, target_lang, eng)
        translated_body = translate_body(body, target_lang, eng, pbar=pbar)
        result = _reattach_body(frontmatter, translated_fm, translated_body)
        return validate_translated_output(result, content, target_lang)

    if engine is not None:
        return _do_translate(engine)

    with create_engine(model) as eng:
        return _do_translate(eng)
