"""Shared translation-engine types, constants, and prompt/budget helpers."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod


DEFAULT_TRANSLATION_MODEL = "tencent/Hy-MT2-1.8B"
DEFAULT_TRANSLATION_MODEL_GGUF = "tencent/Hy-MT2-1.8B-GGUF"
# Ollama tag for the same model. Ollama pulls GGUF straight from HuggingFace via
# the hf.co/ prefix, so no separate conversion step is needed:
#   ollama pull hf.co/tencent/Hy-MT2-1.8B-GGUF
DEFAULT_TRANSLATION_MODEL_OLLAMA = "hf.co/tencent/Hy-MT2-1.8B-GGUF"

SAMPLING_DEFAULTS = {
    "top_k": 20,
    "top_p": 0.6,
    "temperature": 0.7,
    "repetition_penalty": 1.05,
}


def kv_bytes_per_token(config, dtype_bytes: int = 2) -> int | None:
    """Bytes of KV cache one token occupies for the whole model.

    2 (K and V) × layers × kv_heads × head_dim × dtype_bytes. Returns None when
    the config lacks the fields needed to compute it (caller then skips budgeting).
    """
    n_layers = getattr(config, "num_hidden_layers", None)
    hidden = getattr(config, "hidden_size", None)
    n_heads = getattr(config, "num_attention_heads", None)
    n_kv = getattr(config, "num_key_value_heads", None) or n_heads
    head_dim = getattr(config, "head_dim", None) or (
        hidden // n_heads if hidden and n_heads else None
    )
    if not (n_layers and n_kv and head_dim):
        return None
    return 2 * n_layers * n_kv * head_dim * dtype_bytes


def plan_token_budget_batches(
    token_lens: list[int], max_area: float, reserve: int = 0
) -> list[list[int]]:
    """Greedily group prompt indices so each sub-batch's padded token-area stays
    within *max_area*.

    Area of a (left-padded) sub-batch ≈ count × max(effective_len), where
    effective_len = prompt_len + reserve (reserve = max_new_tokens, the KV the
    generation will grow into). Input order is preserved; a single prompt that
    alone exceeds max_area still gets its own group (the memory-fraction backstop
    + reactive OOM-halving handle the rare genuine overflow).
    """
    groups: list[list[int]] = []
    current: list[int] = []
    current_max = 0
    for i, ln in enumerate(token_lens):
        eff = ln + reserve
        new_max = max(current_max, eff)
        if current and (len(current) + 1) * new_max > max_area:
            groups.append(current)
            current, current_max = [], 0
            new_max = eff
        current.append(i)
        current_max = new_max
    if current:
        groups.append(current)
    return groups


def resolve_translation_model(model: str | None = None) -> str:
    return (
        model
        or os.environ.get("GADGET_TRANSLATION_MODEL")
        or DEFAULT_TRANSLATION_MODEL
    ).strip()


def resolve_ollama_translation_model(model: str | None = None) -> str:
    """Ollama model tag for the translator. An explicitly-passed *model* wins when it
    looks like an Ollama tag (has a ``:tag`` or ``hf.co/`` prefix) — this lets the
    translator GUI / ``--model`` point at a specific served model. An HF-repo-style id
    (``org/name``) can't be served by Ollama as-is, so it's ignored in favor of the
    configured tag (``OLLAMA_TRANSLATION_MODEL``, not ``GADGET_TRANSLATION_MODEL`` which
    carries the HF-repo id for the in-process backends)."""
    if model and (":" in model or model.startswith("hf.co/")):
        return model.strip()
    return (
        os.environ.get("OLLAMA_TRANSLATION_MODEL")
        or DEFAULT_TRANSLATION_MODEL_OLLAMA
    ).strip()


class TranslationEngine(ABC):
    """Unified interface for local translation inference."""

    def __init__(self, model_id: str) -> None:
        self.model_id = model_id

    @abstractmethod
    def load(self) -> None:
        """Load model and tokenizer into GPU memory."""

    @abstractmethod
    def generate_batch(
        self,
        prompts: list[str],
        *,
        max_new_tokens: int = 4096,
    ) -> list[str]:
        """Generate completions for a batch of prompts."""

    @abstractmethod
    def unload(self) -> None:
        """Release GPU memory."""

    def __enter__(self) -> TranslationEngine:
        self.load()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.unload()


def build_chat_messages(prompt: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": prompt}]
