"""LLM 后端统一调用层 — re-export shim.

All implementations moved to ``common/``. This module re-exports every public
symbol so that existing ``from llm_backends import ...`` statements continue
to work unchanged.
"""

from common.io import atomic_write as _atomic_write
from common.json_utils import (
    parse_json_response,
    repair_json_with_llm,
    try_repair_result,
)
from common.llm import (
    LLMCallConfig,
    call_llm,
    call_anthropic,
    call_openai,
    call_claude_cli,
    ChunkTimeoutError,
    chunk_text,
    timed_llm_call,
    load_chunk_cache,
    save_chunk_cache,
    cleanup_chunk_cache,
    hierarchical_merge,
)
