"""Shared markdown translation helpers using local inference (vLLM / transformers).

Package layout::

    protect.py      fragment protection, chunking, language detection, prompts
    frontmatter.py  YAML field scan/translate, language gate, Qwen review
    document.py     body + full-document orchestration and validation

``from common.translation import ...`` is unchanged: this ``__init__`` re-exports
the public API that previously lived in a single ``translation.py``.
"""

from common.translation.document import (
    clean_translated_document,
    count_translation_chunks,
    translate_body,
    translate_documents_batch,
    translate_markdown_document,
    validate_translated_output,
)
from common.translation.frontmatter import (
    DEFAULT_REVIEW_MODEL,
    _LABEL_KEYS,
    _LABEL_LIST_KEYS,
    _TRANSLATABLE_KEYS,
    _apply_translated_fields,
    _scan_frontmatter_fields,
    frontmatter_language_mismatches,
    resolve_review_model,
    resolve_review_tag,
    review_frontmatter_fields,
    review_is_enabled,
    sanitize_frontmatter_language,
    translate_frontmatter,
)
from common.translation.protect import (
    FRONTMATTER_RE,
    LANG_NAMES,
    PROTECTED_PATTERNS,
    build_translation_prompt,
    chunk_ceiling,
    detect_language,
    protect_fragments,
    restore_fragments,
    split_frontmatter,
    split_large_text,
    wrong_language,
    zh_path,
)

__all__ = [
    "DEFAULT_REVIEW_MODEL",
    "FRONTMATTER_RE",
    "LANG_NAMES",
    "PROTECTED_PATTERNS",
    "build_translation_prompt",
    "chunk_ceiling",
    "clean_translated_document",
    "count_translation_chunks",
    "detect_language",
    "frontmatter_language_mismatches",
    "protect_fragments",
    "restore_fragments",
    "resolve_review_model",
    "resolve_review_tag",
    "review_frontmatter_fields",
    "review_is_enabled",
    "sanitize_frontmatter_language",
    "split_frontmatter",
    "split_large_text",
    "translate_body",
    "translate_documents_batch",
    "translate_frontmatter",
    "translate_markdown_document",
    "validate_translated_output",
    "wrong_language",
    "zh_path",
    "_LABEL_KEYS",
    "_LABEL_LIST_KEYS",
    "_TRANSLATABLE_KEYS",
    "_apply_translated_fields",
    "_scan_frontmatter_fields",
]
