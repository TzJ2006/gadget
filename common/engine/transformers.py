"""HuggingFace transformers translation backend."""

from __future__ import annotations

import logging
import os

from common.engine.base import (
    SAMPLING_DEFAULTS,
    TranslationEngine,
    build_chat_messages,
    kv_bytes_per_token,
    plan_token_budget_batches,
)

logger = logging.getLogger(__name__)

_DEFAULT_BATCH_SIZE = int(os.environ.get("GADGET_TRANSLATION_BATCH_SIZE", "0"))
# Headroom factor over the raw KV estimate, to cover activations / cublas scratch
# / fragmentation. Budget is divided by this. ponytail: a crude constant — the
# per-process memory fraction (set in load) is the real hard backstop.
_MEM_SAFETY = float(os.environ.get("GADGET_TRANSLATION_MEM_SAFETY", "1.5"))
_CUDA_MEM_FRACTION = float(os.environ.get("GADGET_CUDA_MEM_FRACTION", "0.9"))


class TransformersEngine(TranslationEngine):
    """HuggingFace transformers backend with true batch generation."""

    def __init__(self, model_id: str, device: str | None = None) -> None:
        super().__init__(model_id)
        self._device = device
        self._model = None
        self._tokenizer = None

    def load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        logger.info("Loading model %s with transformers...", self.model_id)

        self._tokenizer = AutoTokenizer.from_pretrained(
            self.model_id, trust_remote_code=True,
        )
        if self._tokenizer.pad_token is None:
            self._tokenizer.pad_token = self._tokenizer.eos_token
        self._tokenizer.padding_side = "left"

        device = self._device
        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"

        dtype = torch.float16 if device == "cuda" else torch.float32
        self._model = AutoModelForCausalLM.from_pretrained(
            self.model_id,
            torch_dtype=dtype,
            device_map=device if device == "cuda" else None,
            attn_implementation="sdpa",
            trust_remote_code=True,
        )
        if device == "cpu":
            self._model = self._model.to(device)
        self._model.eval()

        # Cap torch's allocator at a fraction of VRAM so an over-large batch raises
        # a clean OOM (caught by _generate_chunk's halving) instead of silently
        # spilling to system RAM via the Windows driver's sysmem fallback — which
        # doesn't raise and just makes inference crawl.
        if device == "cuda":
            try:
                torch.cuda.set_per_process_memory_fraction(
                    _CUDA_MEM_FRACTION, self._model.device
                )
            except Exception as exc:  # noqa: BLE001 — never block loading on this
                logger.warning("set_per_process_memory_fraction failed: %s", exc)

        logger.info("Model loaded on %s (%s)", device, dtype)

    def generate_batch(
        self,
        prompts: list[str],
        *,
        max_new_tokens: int = 4096,
    ) -> list[str]:
        if self._model is None or self._tokenizer is None:
            raise RuntimeError("Engine not loaded — call load() first")

        tokenizer = self._tokenizer
        formatted = [
            tokenizer.apply_chat_template(
                build_chat_messages(p), tokenize=False, add_generation_prompt=True,
            )
            for p in prompts
        ]

        if _DEFAULT_BATCH_SIZE:
            # Explicit fixed-size override (backward compat).
            groups = [
                list(range(s, min(s + _DEFAULT_BATCH_SIZE, len(formatted))))
                for s in range(0, len(formatted), _DEFAULT_BATCH_SIZE)
            ]
        else:
            groups = self._plan_subbatches(formatted, max_new_tokens)

        results: list[str | None] = [None] * len(formatted)
        for group in groups:
            sub = [formatted[i] for i in group]
            for idx, out in zip(group, self._generate_chunk(sub, max_new_tokens)):
                results[idx] = out
        return results  # type: ignore[return-value]

    def _plan_subbatches(self, formatted: list[str], max_new_tokens: int) -> list[list[int]]:
        """Split prompts into VRAM-budgeted sub-batches (whole list if not on GPU)."""
        max_area = self._token_area_budget()
        if max_area is None:
            return [list(range(len(formatted)))]
        lens = [len(self._tokenizer.encode(t)) for t in formatted]
        return plan_token_budget_batches(lens, max_area, reserve=max_new_tokens)

    def _token_area_budget(self) -> float | None:
        """Max (batch × padded_len) token-area that fits the VRAM budget. None when
        it can't be computed (CPU / no CUDA / unknown config) → no budgeting."""
        import torch

        if self._model.device.type != "cuda" or not torch.cuda.is_available():
            return None
        per_tok = kv_bytes_per_token(self._model.config)
        if not per_tok:
            return None
        dev = self._model.device
        total = torch.cuda.get_device_properties(dev).total_memory
        budget = _CUDA_MEM_FRACTION * total - torch.cuda.memory_allocated(dev)
        if budget <= 0:
            return None
        return budget / (per_tok * _MEM_SAFETY)

    def _generate_chunk(
        self, texts: list[str], max_new_tokens: int,
    ) -> list[str]:
        import torch

        tokenizer = self._tokenizer
        model = self._model
        current_batch = list(texts)
        while True:
            try:
                inputs = tokenizer(
                    current_batch,
                    return_tensors="pt",
                    padding=True,
                    truncation=True,
                ).to(model.device)
                inputs.pop("token_type_ids", None)
                prompt_len = inputs["input_ids"].shape[1]

                with torch.no_grad():
                    outputs = model.generate(
                        **inputs,
                        max_new_tokens=max_new_tokens,
                        do_sample=True,
                        top_k=SAMPLING_DEFAULTS["top_k"],
                        top_p=SAMPLING_DEFAULTS["top_p"],
                        temperature=SAMPLING_DEFAULTS["temperature"],
                        repetition_penalty=SAMPLING_DEFAULTS["repetition_penalty"],
                    )
                generated = outputs[:, prompt_len:]
                return [
                    # clean_up_tokenization_spaces=False: the default cleanup is
                    # destructive for BPE (strips spaces before punctuation).
                    tokenizer.decode(
                        g, skip_special_tokens=True,
                        clean_up_tokenization_spaces=False,
                    ).strip()
                    for g in generated
                ]
            except RuntimeError as exc:
                if "out of memory" not in str(exc).lower() or len(current_batch) <= 1:
                    raise
                half = max(1, len(current_batch) // 2)
                logger.warning(
                    "OOM with batch size %d, splitting to %d",
                    len(current_batch), half,
                )
                import torch as _torch
                _torch.cuda.empty_cache()
                left = self._generate_chunk(current_batch[:half], max_new_tokens)
                right = self._generate_chunk(current_batch[half:], max_new_tokens)
                return left + right

    def unload(self) -> None:
        if self._model is None:
            return
        del self._model
        del self._tokenizer
        self._model = None
        self._tokenizer = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
        logger.info("Model unloaded")
