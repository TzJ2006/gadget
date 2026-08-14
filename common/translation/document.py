"""Document-level translation: body chunks, validation, batch orchestration."""

from __future__ import annotations

import logging
import re
from typing import Any

from common.engine import TranslationEngine, create_engine
from common.translation.frontmatter import (
    _finalize_translated_fields,
    _scan_frontmatter_fields,
    frontmatter_language_mismatches,
    translate_frontmatter,
)
from common.translation.protect import (
    _reattach_body,
    build_translation_prompt,
    chunk_ceiling,
    protect_fragments,
    restore_fragments,
    split_frontmatter,
    split_large_text,
    wrong_language,
)

logger = logging.getLogger(__name__)

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
    the original, still in the source language at document level, or (when
    *target_lang* is ``en``) still has Chinese title/tags/summary — document-level
    5% CJK misses a leaked Chinese title on a long English body. Chinese pages
    are not field-checked: originally-English titles and proper nouns stay English.
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
    if target_lang == "en":
        fm, _ = split_frontmatter(cleaned)
        mismatches = frontmatter_language_mismatches(fm, target_lang)
        if mismatches:
            keys = ", ".join(sorted(
                {fld[1].strip().rstrip(":") or "-" for fld in mismatches}
            ))
            raise ValueError(
                f"Frontmatter field(s) not in {target_lang}: {keys}"
            )
    return cleaned


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
            result_lines = _finalize_translated_fields(
                plan["fm_lines"], plan["fm_fields"], fm_results, target_lang)
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
