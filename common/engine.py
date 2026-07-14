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
import sys
import time
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)

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

_DEFAULT_BATCH_SIZE = int(os.environ.get("GADGET_TRANSLATION_BATCH_SIZE", "0"))
# Headroom factor over the raw KV estimate, to cover activations / cublas scratch
# / fragmentation. Budget is divided by this. ponytail: a crude constant — the
# per-process memory fraction (set in load) is the real hard backstop.
_MEM_SAFETY = float(os.environ.get("GADGET_TRANSLATION_MEM_SAFETY", "1.5"))
_CUDA_MEM_FRACTION = float(os.environ.get("GADGET_CUDA_MEM_FRACTION", "0.9"))


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


def _ollama_native_host() -> str:
    """Root URL of the local Ollama server (native /api/*), derived from the same
    env the chat backend uses. Strips a trailing /v1 (that's the OpenAI-compat path).

    Default is 127.0.0.1, NOT localhost: on Windows, localhost resolves IPv6-first
    and stalls ~2s per request before falling back to IPv4 (measured in
    test/performance/results/localhost_overhead.json)."""
    base = (os.environ.get("OLLAMA_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or "http://127.0.0.1:11434/v1")
    host = base.rstrip("/")
    if host.endswith("/v1"):
        host = host[:-len("/v1")]
    return host


def _estimate_tokens(text: str) -> int:
    """Conservative token estimate: CJK ≈ 0.7 tok/char, other ≈ 0.35 tok/char."""
    cjk = sum(1 for c in text if "一" <= c <= "鿿")
    return int(cjk * 0.7 + (len(text) - cjk) * 0.35) + 64


def _ollama_tags(host: str, timeout: int = 3) -> list[str] | None:
    """Locally-pulled model tags from GET /api/tags. None if the server is unreachable."""
    import json
    import urllib.request

    try:
        with urllib.request.urlopen(host + "/api/tags", timeout=timeout) as resp:
            return [m.get("model", "") for m in json.load(resp).get("models", [])]
    except Exception:  # noqa: BLE001 — any failure means "not available"
        return None


def _model_in_tags(model: str, tags: list[str]) -> bool:
    """Match a requested tag against pulled tags, tolerating the :tag suffix
    (a bare `foo/bar` request matches a resident `foo/bar:latest`)."""
    base = model.split(":")[0]
    return any(t == model or t.split(":")[0] == base for t in tags)


# ---------------------------------------------------------------------------
# Abstract engine
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Prompt helpers (shared by both backends)
# ---------------------------------------------------------------------------

def build_chat_messages(prompt: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": prompt}]


# ---------------------------------------------------------------------------
# transformers backend
# ---------------------------------------------------------------------------

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
        import torch

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


# ---------------------------------------------------------------------------
# vLLM backend
# ---------------------------------------------------------------------------

class VLLMEngine(TranslationEngine):
    """vLLM offline batch inference backend."""

    def __init__(self, model_id: str) -> None:
        super().__init__(model_id)
        self._llm = None
        self._tokenizer = None

    def load(self) -> None:
        if self._llm is not None:
            return
        from vllm import LLM
        from transformers import AutoTokenizer

        logger.info("Loading model %s with vLLM...", self.model_id)
        self._llm = LLM(
            model=self.model_id,
            trust_remote_code=True,
            dtype="half",
            max_model_len=8192,
        )
        self._tokenizer = AutoTokenizer.from_pretrained(
            self.model_id, trust_remote_code=True,
        )
        logger.info("vLLM engine ready")

    def is_alive(self) -> bool:
        if self._llm is None:
            return False
        try:
            return self._llm.llm_engine is not None
        except Exception:
            return False

    def generate_batch(
        self,
        prompts: list[str],
        *,
        max_new_tokens: int = 4096,
    ) -> list[str]:
        from vllm import SamplingParams

        if self._llm is None or self._tokenizer is None:
            raise RuntimeError("Engine not loaded — call load() first")

        formatted = [
            self._tokenizer.apply_chat_template(
                build_chat_messages(p), tokenize=False, add_generation_prompt=True,
            )
            for p in prompts
        ]

        params = SamplingParams(
            max_tokens=max_new_tokens,
            top_k=SAMPLING_DEFAULTS["top_k"],
            top_p=SAMPLING_DEFAULTS["top_p"],
            temperature=SAMPLING_DEFAULTS["temperature"],
            repetition_penalty=SAMPLING_DEFAULTS["repetition_penalty"],
        )

        outputs = self._llm.generate(formatted, params)
        return [out.outputs[0].text.strip() for out in outputs]

    def unload(self) -> None:
        if self._llm is None:
            return
        del self._llm
        del self._tokenizer
        self._llm = None
        self._tokenizer = None
        logger.info("vLLM engine unloaded")



# ---------------------------------------------------------------------------
# llama-cpp-python (GGUF) backend
# ---------------------------------------------------------------------------

class LlamaCppEngine(TranslationEngine):
    """llama-cpp-python backend for GGUF models - fast, low-memory, no PyTorch needed."""

    def __init__(self, model_id: str, n_gpu_layers: int = -1) -> None:
        super().__init__(model_id)
        self._n_gpu_layers = n_gpu_layers
        self._llm = None
        self._chat_template = None

    def load(self) -> None:
        if self._llm is not None:
            return
        from llama_cpp import Llama

        gguf_path = self._resolve_gguf_path()
        logger.info("Loading GGUF model from %s (n_gpu_layers=%d)...", gguf_path, self._n_gpu_layers)

        self._llm = Llama(
            model_path=str(gguf_path),
            # translate_body feeds chunks up to split_large_text's 7000-char ceiling
            # (~4.5k tokens CJK) and asks for up to 4096 output tokens. n_ctx=4096 could
            # not hold prompt+output, so the first/largest chunk overflowed and the head
            # of long docs was silently dropped. 16k fits both with headroom (model
            # trains at 262144). ponytail: bump toward chunk_ceiling+max_new_tokens if you
            # raise either.
            n_ctx=16384,
            n_gpu_layers=self._n_gpu_layers,
            verbose=False,
        )
        logger.info("GGUF model loaded")

    def _resolve_gguf_path(self) -> str:
        """Resolve model_id to a local .gguf file path.

        Supports: direct .gguf path, or HuggingFace repo id (auto-downloads via huggingface_hub).
        """
        import pathlib

        if pathlib.Path(self.model_id).suffix == ".gguf":
            return self.model_id

        from huggingface_hub import hf_hub_download, list_repo_files

        files = list_repo_files(self.model_id)
        gguf_files = [f for f in files if f.endswith(".gguf")]
        if not gguf_files:
            raise FileNotFoundError(f"No .gguf files found in repo {self.model_id}")

        # Prefer Q4_K_M for balance of speed and quality, else first available
        preferred = [f for f in gguf_files if "Q4_K_M" in f.upper()]
        chosen = preferred[0] if preferred else gguf_files[0]

        logger.info("Downloading %s/%s...", self.model_id, chosen)
        return hf_hub_download(repo_id=self.model_id, filename=chosen)

    def generate_batch(
        self,
        prompts: list[str],
        *,
        max_new_tokens: int = 4096,
    ) -> list[str]:
        if self._llm is None:
            raise RuntimeError("Engine not loaded — call load() first")

        results: list[str] = []
        for prompt in prompts:
            messages = build_chat_messages(prompt)
            output = self._llm.create_chat_completion(
                messages=messages,
                max_tokens=max_new_tokens,
                top_k=SAMPLING_DEFAULTS["top_k"],
                top_p=SAMPLING_DEFAULTS["top_p"],
                temperature=SAMPLING_DEFAULTS["temperature"],
                repeat_penalty=SAMPLING_DEFAULTS["repetition_penalty"],
            )
            text = output["choices"][0]["message"]["content"] or ""
            results.append(text.strip())
        return results

    def unload(self) -> None:
        if self._llm is None:
            return
        del self._llm
        self._llm = None
        logger.info("GGUF engine unloaded")

# ---------------------------------------------------------------------------
# Ollama backend (native /api/chat over the local server, stdlib only)
# ---------------------------------------------------------------------------

class OllamaEngine(TranslationEngine):
    """Translation via a local Ollama server — no in-process model load.

    The model lives in the Ollama server (shared with the summarize chat model),
    so this backend costs no extra process VRAM and needs no torch/vllm/llama-cpp.
    Sampling mirrors SAMPLING_DEFAULTS so output matches the in-process GGUF backend.
    Uses the native /api/chat endpoint (stdlib urllib) for precise `options` control.
    """

    # The Ollama template auto-derived from the HY-MT2 GGUF is corrupt (it never
    # inserts the user prompt), so /api/chat feeds the model an empty prompt and
    # it hallucinates. For HY models we format the real chat template ourselves
    # (from tencent/Hy-MT2-1.8B chat_template.jinja) and call /api/generate raw.
    _HY_TEMPLATE = "<｜hy_begin▁of▁sentence｜><｜hy_User｜>{prompt}<｜hy_Assistant｜>"
    _HY_STOP = ["<｜hy_place▁holder▁no▁2｜>", "<｜hy_end▁of▁sentence｜>"]

    def __init__(self, model_id: str, *, timeout: int | None = None) -> None:
        super().__init__(model_id)
        self._host = _ollama_native_host()
        self._timeout = timeout or int(os.environ.get("OLLAMA_TRANSLATION_TIMEOUT", "300"))
        self._raw_hy = "hy-mt" in model_id.lower()

    def load(self) -> None:
        # Fail loud up front (server down / model not pulled) rather than erroring
        # per-chunk mid-translation. Callers that select ollama explicitly get a
        # clear pull hint; the auto-detect path pre-gates on _ollama_available().
        tags = _ollama_tags(self._host, timeout=5)
        if tags is None:
            raise RuntimeError(
                f"Ollama server not reachable at {self._host} for translation. "
                f"Start Ollama, or set GADGET_TRANSLATION_BACKEND=llamacpp/transformers "
                f"to translate in-process."
            )
        if not _model_in_tags(self.model_id, tags):
            raise RuntimeError(
                f"Ollama has no model '{self.model_id}'. Pull it first:\n"
                f"    ollama pull {self.model_id}\n"
                f"(available: {', '.join(tags) or 'none'})"
            )
        logger.info("Using Ollama translation backend: %s @ %s", self.model_id, self._host)

    def generate_batch(
        self,
        prompts: list[str],
        *,
        max_new_tokens: int = 4096,
    ) -> list[str]:
        options = {
            "temperature": SAMPLING_DEFAULTS["temperature"],
            "top_p": SAMPLING_DEFAULTS["top_p"],
            "top_k": SAMPLING_DEFAULTS["top_k"],
            "repeat_penalty": SAMPLING_DEFAULTS["repetition_penalty"],
            "num_predict": max_new_tokens,
        }
        # 8192 fits every chunk the pipeline sends (EN chunks capped at 7000 chars
        # ≈ 1.8k tokens, zh chunks at 5000 chars ≈ 3.3k tokens — see
        # common.translation.chunk_ceiling) plus the 4096 output budget, AND keeps
        # this model small enough (3.6GB vs 6.1GB at 16384, measured) to stay
        # co-resident with the 24GB summarize chat model on a 32GB GPU instead of
        # evicting it (~10s reload per summarize↔translate switch). Raise via env
        # if you feed oversized chunks from outside the pipeline's chunkers.
        options["num_ctx"] = int(os.environ.get("OLLAMA_TRANSLATION_NUM_CTX", "8192"))

        # Ollama decodes concurrent requests in one batched pass (n_seq ≥ 8
        # measured for HY-MT2), so 4 workers ≈ 2.2× wall-clock on real chunk sets
        # (test/performance/reports/performance_plan.md §M2). 1 = sequential
        # (pre-concurrency behavior / rollback knob).
        workers = int(os.environ.get("GADGET_TRANSLATION_CONCURRENCY", "4"))
        t0 = time.monotonic()
        if workers <= 1 or len(prompts) <= 1:
            metas = [self._generate_one(p, options) for p in prompts]
        else:
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(min(workers, len(prompts))) as pool:
                metas = list(pool.map(lambda p: self._generate_one(p, options), prompts))
        elapsed = time.monotonic() - t0
        gen_tokens = sum(m[1] for m in metas)
        logger.info(
            "Ollama translation: %d prompt(s), workers=%d, %.1fs, %d gen tokens"
            " (%.0f tok/s aggregate, model load %.1fs)",
            len(prompts), workers, elapsed, gen_tokens,
            gen_tokens / elapsed if elapsed > 0 else 0.0,
            max((m[2] for m in metas), default=0.0),
        )
        return [m[0] for m in metas]

    def _generate_one(self, prompt: str, options: dict) -> tuple[str, int, float]:
        """One Ollama request. Returns (text, eval_count, load_seconds)."""
        import json
        import urllib.request

        # Belt-and-braces: the chunkers cap chunk sizes so prompt + num_predict
        # fits num_ctx, but an oversized prompt from an unchunked caller would be
        # silently left-truncated by Ollama. Grow the context for THIS request
        # instead (may briefly evict co-resident models — rare by design).
        est_total = _estimate_tokens(prompt) + int(options.get("num_predict") or 0)
        if est_total > options.get("num_ctx", 0):
            bumped = min(32768, 1 << (est_total - 1).bit_length())
            logger.warning(
                "Prompt estimated at %d tokens exceeds num_ctx=%d — raising to %d "
                "for this request", est_total, options.get("num_ctx", 0), bumped)
            options = {**options, "num_ctx": bumped}

        if self._raw_hy:
            body = {
                "model": self.model_id,
                "prompt": self._HY_TEMPLATE.format(prompt=prompt),
                "raw": True,
                "stream": False,
                "options": {**options, "stop": self._HY_STOP},
            }
            endpoint = "/api/generate"
        else:
            body = {
                "model": self.model_id,
                "messages": build_chat_messages(prompt),
                "stream": False,
                "options": options,
            }
            endpoint = "/api/chat"
        # Request-level keep_alive (same knob name as the server env var): keep the
        # small translator resident between pipeline stages instead of Ollama's
        # 5-minute idle unload. _free_ollama_vram still evicts it on demand when an
        # in-process engine needs the GPU.
        body["keep_alive"] = os.environ.get("OLLAMA_KEEP_ALIVE", "30m")
        req = urllib.request.Request(
            self._host + endpoint, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            data = json.load(resp)
        text = data.get("response") if self._raw_hy else data.get("message", {}).get("content")
        return ((text or "").strip(), data.get("eval_count") or 0,
                (data.get("load_duration") or 0) / 1e9)

    def unload(self) -> None:
        # The model is owned by the Ollama server; nothing to release in-process.
        pass


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

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


def _vllm_available() -> bool:
    if sys.platform == "win32":
        return False
    try:
        import vllm  # noqa: F401
        return True
    except ImportError:
        return False


def _llamacpp_available() -> bool:
    try:
        import llama_cpp  # noqa: F401
        return True
    except ImportError:
        return False


def _ollama_available(model: str) -> bool:
    """True when a local Ollama server is up AND has *model* pulled — the gate for
    auto-preferring ollama without breaking boxes that lack it."""
    tags = _ollama_tags(_ollama_native_host())
    return tags is not None and _model_in_tags(model, tags)


def _free_ollama_vram() -> None:
    """Best-effort: unload models a local Ollama server is holding, before we
    load a translation model onto the same GPU.

    On a single-GPU box the summarizer's resident model (e.g. ~23GB for
    qwen3.6-35B) leaves little room for the GGUF translator, so both co-resident
    can hit the VRAM ceiling. Freeing it first avoids the OOM. Probes the local
    Ollama endpoint (OLLAMA_BASE_URL > OPENAI_BASE_URL > 127.0.0.1:11434); if
    nothing is there the /api/ps probe fails fast and this no-ops. All errors
    swallowed.

    Evicting Ollama means the *next* summarize call cold-reloads (~8s); set
    GADGET_KEEP_OLLAMA=1 to skip eviction on boxes where co-residence fits (multi-GPU
    or small chat model) and that reload costs more than the VRAM it frees.
    """
    import json
    import urllib.request

    if os.environ.get("GADGET_KEEP_OLLAMA", "").strip().lower() in ("1", "true", "yes"):
        logger.debug("GADGET_KEEP_OLLAMA set — skipping Ollama VRAM eviction")
        return

    base = (os.environ.get("OLLAMA_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or "http://127.0.0.1:11434/v1")
    host = base.rstrip("/")
    if host.endswith("/v1"):
        host = host[:-len("/v1")]

    try:  # which models are resident? fall back to the configured one.
        with urllib.request.urlopen(host + "/api/ps", timeout=3) as resp:
            loaded = [m.get("model") for m in json.load(resp).get("models", [])]
    except Exception:
        loaded = []
    if not loaded:
        cfg = os.environ.get("OLLAMA_MODEL") or os.environ.get("OPENAI_MODEL")
        loaded = [cfg] if cfg else []

    for model in filter(None, loaded):
        try:  # keep_alive=0 tells Ollama to unload immediately
            req = urllib.request.Request(
                host + "/api/generate",
                data=json.dumps({"model": model, "keep_alive": 0}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5).read()
            logger.info("Freed Ollama VRAM: unloaded %s", model)
        except Exception:
            pass


# Explicit GADGET_TRANSLATION_BACKEND values. Empty/unset = auto-select.
_TRANSLATION_BACKENDS = ("ollama", "vllm", "transformers", "llamacpp")


def create_engine(model: str | None = None) -> TranslationEngine:
    """Create or retrieve a cached translation engine for this platform.

    The engine is loaded once and reused across all callers in the same
    process. Use shutdown_engines() to explicitly release GPU memory.
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
            # models (_free_ollama_vram) and loads its own weights — surprising
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
        _free_ollama_vram()
    eng.load()
    _engine_cache[cache_key] = eng
    return _CachedEngineProxy(eng)


def shutdown_engines() -> None:
    """Unload all cached engines and release GPU memory."""
    for eng in _engine_cache.values():
        eng.unload()
    _engine_cache.clear()
