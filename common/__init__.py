"""Common utilities shared across gadget tools."""

from common.io import atomic_write, content_hash, load_json_config
from common.cache import DiskCache
from common.json_utils import (
    parse_json_response,
    try_parse_json,
    try_repair_result,
    repair_json_with_llm,
)
from common.llm import (
    call_llm,
    call_llm_raw,
    call_anthropic,
    call_openai,
    call_claude_cli,
    LLMCallConfig,
    ChunkTimeoutError,
    chunk_text,
    timed_llm_call,
    hierarchical_merge,
    load_chunk_cache,
    save_chunk_cache,
    cleanup_chunk_cache,
    ANTHROPIC_MODELS,
    OPENAI_MODELS,
)
from common.hugo import run_hugo_update
from common.engine import (
    TranslationEngine,
    TransformersEngine,
    VLLMEngine,
    LlamaCppEngine,
    OllamaEngine,
    create_engine,
    resolve_translation_model,
    DEFAULT_TRANSLATION_MODEL,
    SAMPLING_DEFAULTS,
)
from common.paths import GADGET_ROOT, OUTPUTS_DIR, REPORTS_DIR, LOGS_DIR, CACHE_DIR, DATA_DIR
from common.site_staging import (
    resolve_site_staging_root,
    resolve_site_content_dir,
    resolve_site_static_dir,
    write_site_content,
    copy_site_static,
)
from common.translation import (
    FRONTMATTER_RE,
    LANG_NAMES,
    PROTECTED_PATTERNS,
    clean_translated_document,
    count_translation_chunks,
    detect_language,
    protect_fragments,
    restore_fragments,
    split_frontmatter,
    split_large_text,
    translate_body,
    translate_frontmatter,
    translate_markdown_document,
    validate_translated_output,
    zh_path,
)

__all__ = [
    "atomic_write", "content_hash", "load_json_config",
    "DiskCache",
    "parse_json_response", "try_parse_json", "try_repair_result", "repair_json_with_llm",
    "call_llm", "call_llm_raw", "call_anthropic", "call_openai", "call_claude_cli",
    "LLMCallConfig", "ChunkTimeoutError", "chunk_text", "timed_llm_call",
    "hierarchical_merge", "load_chunk_cache", "save_chunk_cache", "cleanup_chunk_cache",
    "ANTHROPIC_MODELS", "OPENAI_MODELS",
    "TranslationEngine", "TransformersEngine", "VLLMEngine", "LlamaCppEngine", "OllamaEngine",
    "create_engine", "resolve_translation_model",
    "DEFAULT_TRANSLATION_MODEL", "SAMPLING_DEFAULTS",
    "FRONTMATTER_RE", "LANG_NAMES", "PROTECTED_PATTERNS",
    "clean_translated_document", "count_translation_chunks", "detect_language",
    "protect_fragments", "restore_fragments", "split_frontmatter", "split_large_text",
    "translate_body", "translate_frontmatter", "translate_markdown_document",
    "validate_translated_output", "zh_path",
    "run_hugo_update",
    "resolve_site_staging_root", "resolve_site_content_dir", "resolve_site_static_dir",
    "write_site_content", "copy_site_static",
    "GADGET_ROOT", "OUTPUTS_DIR", "REPORTS_DIR", "LOGS_DIR", "CACHE_DIR", "DATA_DIR",
]
