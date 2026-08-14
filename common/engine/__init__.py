"""Local translation inference engine with ollama, vLLM, llama-cpp-python, and transformers backends.

Provides batch inference for tencent/Hy-MT2-1.8B (or any causal LM).
Backend selection (GADGET_TRANSLATION_BACKEND, else auto): ollama is preferred when a
local Ollama server has the model pulled (no extra process VRAM, shared with the chat
model); else vLLM on Linux (continuous batching), llama-cpp-python (GGUF) on Windows,
transformers as the fallback.
"""

from __future__ import annotations

import logging
import os

from common.engine.base import (
    DEFAULT_TRANSLATION_MODEL,
    DEFAULT_TRANSLATION_MODEL_GGUF,
    DEFAULT_TRANSLATION_MODEL_OLLAMA,
    SAMPLING_DEFAULTS,
    TranslationEngine,
    build_chat_messages,
    kv_bytes_per_token,
    plan_token_budget_batches,
    resolve_ollama_translation_model,
    resolve_translation_model,
)
from common.engine.llamacpp import LlamaCppEngine, _llamacpp_available
from common.engine.ollama import (
    OllamaEngine,
    _model_in_tags,
    _ollama_available,
    _ollama_tags,
    free_ollama_vram,
    ollama_native_host,
)
from common.engine.transformers import TransformersEngine
from common.engine.vllm import VLLMEngine, _vllm_available

logger = logging.getLogger(__name__)

# Underscore aliases so `from common.engine import _free_ollama_vram` still works.
_ollama_native_host = ollama_native_host
_free_ollama_vram = free_ollama_vram

# Keyed by (GADGET_TRANSLATION_BACKEND value, resolved model id); "" backend = auto.
_engine_cache: dict[tuple[str, str], TranslationEngine] = {}


class _CachedEngineProxy:
    """Wraps a cached engine so context-manager exit doesn't unload it."""

    def __init__(self, engine: TranslationEngine) -> None:
        self._engine = engine

    def __getattr__(self, name: str):
        return getattr(self._engine, name)

    def __enter__(self) -> TranslationEngine:
        return self._engine

    def __exit__(self, exc_type, exc, tb) -> None:
        pass


# Explicit GADGET_TRANSLATION_BACKEND values. Empty/unset = auto-select.
_TRANSLATION_BACKENDS = ("ollama", "vllm", "transformers", "llamacpp")


def create_engine(model: str | None = None) -> TranslationEngine:
    """Create or retrieve a cached translation engine for this platform.

    The engine is loaded once and reused across all callers in the same process.
    """
    model_id = resolve_translation_model(model)
    backend = os.environ.get("GADGET_TRANSLATION_BACKEND", "").strip().lower()
    if backend and backend not in _TRANSLATION_BACKENDS:
        raise ValueError(
            f"Unknown GADGET_TRANSLATION_BACKEND {backend!r}; "
            f"valid: {_TRANSLATION_BACKENDS} (or unset for auto-select)")
    # Key the cache by (backend, model): switching GADGET_TRANSLATION_BACKEND
    # mid-process must not hand back an engine built for the previous backend.
    cache_key = (backend, model_id)

    if cache_key in _engine_cache:
        cached = _engine_cache[cache_key]
        if hasattr(cached, "is_alive") and not cached.is_alive():
            logger.warning("Cached engine for %s is dead, recreating...", cache_key)
            del _engine_cache[cache_key]
        else:
            return _CachedEngineProxy(cached)

    ollama_model = resolve_ollama_translation_model(model)

    if backend == "ollama":
        eng = OllamaEngine(ollama_model)
    elif backend == "vllm":
        eng = VLLMEngine(model_id)
    elif backend == "transformers":
        eng = TransformersEngine(model_id)
    elif backend == "llamacpp":
        gguf_model = os.environ.get("GADGET_TRANSLATION_MODEL") or DEFAULT_TRANSLATION_MODEL_GGUF
        eng = LlamaCppEngine(gguf_model)
    elif model_id == DEFAULT_TRANSLATION_MODEL and _ollama_available(ollama_model):
        # Auto-prefer ollama only for the DEFAULT model — a caller that overrode the
        # model (create_engine(model=...) or GADGET_TRANSLATION_MODEL) wants that
        # specific model, which only the in-process backends honor. Set
        # GADGET_TRANSLATION_BACKEND=ollama to force ollama regardless.
        logger.info("Using Ollama backend (translation via local server)")
        eng = OllamaEngine(ollama_model)
    else:
        if not backend and model_id == DEFAULT_TRANSLATION_MODEL:
            # Loud fallback: the silent in-process path evicts Ollama's resident
            # models (free_ollama_vram) and loads its own weights — surprising
            # and slower. Tell the user how to get the shared-server path back.
            logger.warning(
                "Ollama not reachable (or tag %s not pulled) — falling back to an "
                "in-process translation backend. For the faster shared-server "
                "path: ollama pull %s", ollama_model, ollama_model)
        if _vllm_available():
            logger.info("Using vLLM backend")
            eng = VLLMEngine(model_id)
        elif _llamacpp_available():
            logger.info("Using llama-cpp-python backend (GGUF)")
            gguf_model = DEFAULT_TRANSLATION_MODEL_GGUF if model_id == DEFAULT_TRANSLATION_MODEL else model_id
            eng = LlamaCppEngine(gguf_model)
        else:
            logger.info("Using transformers backend")
            eng = TransformersEngine(model_id)

    # Only evict Ollama when we're about to grab the GPU in-process — never when the
    # translator IS the Ollama server (that would unload the model we just called).
    if not isinstance(eng, OllamaEngine):
        free_ollama_vram()
    eng.load()
    _engine_cache[cache_key] = eng
    return _CachedEngineProxy(eng)


def shutdown_engines() -> None:
    """Unload all cached engines and release GPU memory."""
    for eng in _engine_cache.values():
        eng.unload()
    _engine_cache.clear()


__all__ = [
    "DEFAULT_TRANSLATION_MODEL",
    "DEFAULT_TRANSLATION_MODEL_GGUF",
    "DEFAULT_TRANSLATION_MODEL_OLLAMA",
    "SAMPLING_DEFAULTS",
    "TranslationEngine",
    "TransformersEngine",
    "VLLMEngine",
    "LlamaCppEngine",
    "OllamaEngine",
    "create_engine",
    "shutdown_engines",
    "resolve_translation_model",
    "resolve_ollama_translation_model",
    "build_chat_messages",
    "kv_bytes_per_token",
    "plan_token_budget_batches",
    "ollama_native_host",
    "free_ollama_vram",
]
