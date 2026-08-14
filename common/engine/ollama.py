"""Ollama translation backend (native /api/chat, stdlib only) and host helpers."""

from __future__ import annotations

import logging
import os
import time

from common.engine.base import SAMPLING_DEFAULTS, TranslationEngine, build_chat_messages

logger = logging.getLogger(__name__)


def ollama_native_host() -> str:
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


_ollama_native_host = ollama_native_host


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


def _ollama_available(model: str) -> bool:
    """True when a local Ollama server is up AND has *model* pulled — the gate for
    auto-preferring ollama without breaking boxes that lack it."""
    tags = _ollama_tags(ollama_native_host())
    return tags is not None and _model_in_tags(model, tags)


def free_ollama_vram() -> None:
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

    host = ollama_native_host()

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


_free_ollama_vram = free_ollama_vram


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
        self._host = ollama_native_host()
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
        # 5-minute idle unload. free_ollama_vram still evicts it on demand when an
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
