"""Ollama translation backend (native /api/chat, stdlib only) and host helpers."""

from __future__ import annotations

import ipaddress
import logging
import os
import time
from urllib.parse import urlparse

from common.engine.base import SAMPLING_DEFAULTS, TranslationEngine, build_chat_messages

logger = logging.getLogger(__name__)

_DEFAULT_OLLAMA_BASE = "http://127.0.0.1:11434/v1"


def llm_route() -> str:
    """Explicit text route. Empty means callers choose a backend themselves."""
    return (os.environ.get("GADGET_LLM_ROUTE") or os.environ.get("LC_LLM_ROUTE") or "").strip().lower()


def _host_is_local(host: str) -> bool:
    name = (host or "").strip().lower().strip("[]")
    if name in {"localhost", "127.0.0.1", "::1"} or name.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    return bool(address.is_private or address.is_loopback or address.is_link_local)


def _is_local_http(url: str) -> bool:
    parsed = urlparse(url if "://" in url else "http://" + url)
    return _host_is_local(parsed.hostname or "")


def resolve_local_ollama_base() -> str:
    """OpenAI-compatible base URL for a local Ollama server.

    A public ``OPENAI_BASE_URL`` is ignored. A public ``OLLAMA_BASE_URL`` raises.
    The local client never sends text to a cloud host.
    """
    explicit = os.environ.get("OLLAMA_BASE_URL", "").strip().rstrip("/")
    if explicit:
        if not _is_local_http(explicit):
            raise RuntimeError("OLLAMA_BASE_URL 不是本机或局域网地址，已拒绝把文本发到该地址。")
        return explicit if explicit.endswith("/v1") else explicit + "/v1"
    compat = os.environ.get("OPENAI_BASE_URL", "").strip().rstrip("/")
    if compat and _is_local_http(compat):
        return compat if compat.endswith("/v1") else compat + "/v1"
    return _DEFAULT_OLLAMA_BASE


def ollama_native_host() -> str:
    """Root URL of the local Ollama server (native /api/*). Strips a trailing /v1.

    Default is 127.0.0.1, NOT localhost: on Windows, localhost resolves IPv6-first
    and stalls ~2s per request before falling back to IPv4 (measured in
    test/performance/results/localhost_overhead.json)."""
    host = resolve_local_ollama_base().rstrip("/")
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


def free_ollama_vram() -> tuple[bool, str]:
    """Ask the shared authority to unload this Ollama instance.

    GADGET_KEEP_OLLAMA=1 does not unload and does not free the residency slot.
    A probe failure or another active caller leaves the models loaded.
    Unmanaged GPU processes are not killed.
    """
    import json
    import urllib.request

    if os.environ.get("GADGET_KEEP_OLLAMA", "").strip().lower() in ("1", "true", "yes"):
        logger.debug("GADGET_KEEP_OLLAMA set — skipping Ollama VRAM eviction")
        return False, "GADGET_KEEP_OLLAMA 已设置，未卸载，驻留槽仍保留"

    try:
        from model_access.resources import evict_endpoint
    except ImportError as exc:
        logger.warning("未安装 model_access，拒绝卸载 Ollama")
        return False, "未安装 model_access，拒绝卸载 Ollama"

    host = ollama_native_host()

    def _unload(model: str) -> bool:
        try:
            req = urllib.request.Request(
                host + "/api/generate",
                data=json.dumps({"model": model, "keep_alive": 0}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=5).read()
            logger.info("Freed Ollama VRAM: unloaded %s", model)
            return True
        except Exception:
            return False

    ok, reason = evict_endpoint("gadget-engine", host, unload=_unload)
    if not ok:
        logger.warning("Ollama unload was not confirmed: %s", reason)
    return ok, reason


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

    def _admit(self):
        try:
            from model_access.resources import require_local
        except ImportError as exc:
            raise RuntimeError(
                "未安装 model_access，拒绝在没有统一 GPU 租约的情况下加载模型。"
            ) from exc
        if getattr(self, "_lease_id", ""):
            return
        gate = require_local(
            self.model_id, holder="gadget-engine", backend="ollama", endpoint=self._host, purpose="text",
        )
        self._lease_id = gate.lease_id

    def load(self) -> None:
        # Fail loud up front (server down / model not pulled) rather than erroring
        # per-chunk mid-translation. Callers that select ollama explicitly get a
        # clear pull hint; the auto-detect path pre-gates on _ollama_available().
        self._admit()
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
        self._admit()
        options = {
            "temperature": SAMPLING_DEFAULTS["temperature"],
            "top_p": SAMPLING_DEFAULTS["top_p"],
            "top_k": SAMPLING_DEFAULTS["top_k"],
            "repeat_penalty": SAMPLING_DEFAULTS["repetition_penalty"],
            "num_predict": max_new_tokens,
        }
        # 8192 fits every chunk the pipeline sends (EN chunks capped at 7000 chars
        # ≈ 1.8k tokens, zh chunks at 5000 chars ≈ 3.3k tokens — see
        # common.translation.chunk_ceiling) plus the 4096 output budget. Raise via
        # env if you feed oversized chunks from outside the pipeline's chunkers.
        # ponytail: known ceiling — translation now shares the chat model, and a
        # num_ctx that differs from the one the chat runner was loaded with makes
        # Ollama reload the runner on each summarize↔translate switch (~10s). Set
        # OLLAMA_TRANSLATION_NUM_CTX to the chat variant's num_ctx if that churn
        # shows up; the cost is KV-cache VRAM on every translate call.
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
                # Thinking OFF. Now that translation runs on the general chat model,
                # a reasoning model (gemma4, qwen3.x) spends the entire num_predict
                # budget in `thinking` and returns EMPTY content with
                # done_reason=length — measured: 0 chars out for a 2.7k-char chunk.
                # Translation is a mechanical rewrite; the think phase buys nothing.
                # Ollama accepts this field even on models without thinking support.
                "think": False,
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
        # The server still owns the weights. Drop our use lease only.
        lease_id = getattr(self, "_lease_id", "")
        self._lease_id = ""
        if not lease_id:
            return
        try:
            from model_access.resources import ResourceBoard
        except ImportError:
            return
        ResourceBoard().release(lease_id)
