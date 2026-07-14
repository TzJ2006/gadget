"""OllamaEngine + factory selection — no network, no model load."""

import json

import common.engine as engine


class _FakeResp:
    """Minimal urlopen() stand-in: context manager whose read() returns bytes."""

    def __init__(self, payload: dict):
        self._payload = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_model_in_tags_tolerates_suffix():
    assert engine._model_in_tags("hf.co/x/y", ["hf.co/x/y:latest"])
    assert engine._model_in_tags("qwen3.6:35b", ["qwen3.6:35b"])
    assert not engine._model_in_tags("a/b", ["c/d:latest"])


def test_generate_batch_builds_request_and_parses(monkeypatch):
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["url"] = req.full_url
        seen["body"] = json.loads(req.data)
        return _FakeResp({"response": "  译文  "})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.delenv("OLLAMA_TRANSLATION_NUM_CTX", raising=False)
    monkeypatch.delenv("OLLAMA_KEEP_ALIVE", raising=False)
    eng = engine.OllamaEngine("hf.co/tencent/Hy-MT2-1.8B-GGUF")

    out = eng.generate_batch(["translate me"], max_new_tokens=256)

    assert out == ["译文"]  # response extracted + stripped
    # HY-MT models bypass Ollama's (corrupt) chat template: raw /api/generate
    # with the hand-built Hunyuan prompt.
    assert seen["url"].endswith("/api/generate")
    assert seen["body"]["raw"] is True
    assert "<｜hy_User｜>translate me<｜hy_Assistant｜>" in seen["body"]["prompt"]
    assert seen["body"]["model"] == "hf.co/tencent/Hy-MT2-1.8B-GGUF"
    assert seen["body"]["options"]["num_predict"] == 256
    assert seen["body"]["options"]["temperature"] == engine.SAMPLING_DEFAULTS["temperature"]
    # co-residency default: small enough to live beside the 24GB chat model
    assert seen["body"]["options"]["num_ctx"] == 8192
    # request-level residency: don't idle-unload after Ollama's 5-minute default
    assert seen["body"]["keep_alive"] == "30m"


def _echoing_urlopen(req, timeout=None):
    """Derive the response from the request so concurrent calls need no shared state."""
    body = json.loads(req.data)
    prompt = body["prompt"].split("hy_User｜>")[1].split("<｜hy_Assistant")[0]
    return _FakeResp({"response": f"tr:{prompt}"})


def test_generate_batch_concurrent_preserves_order(monkeypatch):
    monkeypatch.setenv("GADGET_TRANSLATION_CONCURRENCY", "4")
    monkeypatch.setattr("urllib.request.urlopen", _echoing_urlopen)
    eng = engine.OllamaEngine("hf.co/tencent/Hy-MT2-1.8B-GGUF")

    prompts = [f"p{i}" for i in range(6)]
    assert eng.generate_batch(prompts) == [f"tr:p{i}" for i in range(6)]


def test_generate_batch_sequential_rollback_knob(monkeypatch):
    """GADGET_TRANSLATION_CONCURRENCY=1 restores the pre-concurrency behavior."""
    monkeypatch.setenv("GADGET_TRANSLATION_CONCURRENCY", "1")
    monkeypatch.setattr("urllib.request.urlopen", _echoing_urlopen)
    eng = engine.OllamaEngine("hf.co/tencent/Hy-MT2-1.8B-GGUF")

    assert eng.generate_batch(["a", "b", "c"]) == ["tr:a", "tr:b", "tr:c"]


def test_oversized_prompt_bumps_num_ctx(monkeypatch):
    """An unchunked oversized prompt grows num_ctx for that request instead of
    letting Ollama silently left-truncate it at the 8192 default."""
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["body"] = json.loads(req.data)
        return _FakeResp({"response": "ok"})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.delenv("OLLAMA_TRANSLATION_NUM_CTX", raising=False)
    eng = engine.OllamaEngine("hf.co/tencent/Hy-MT2-1.8B-GGUF")

    eng.generate_batch(["中" * 12000])  # ~8.5k tokens est + 4096 predict > 8192
    assert seen["body"]["options"]["num_ctx"] == 16384


def test_factory_selects_ollama_when_backend_env_set(monkeypatch):
    engine._engine_cache.clear()
    monkeypatch.setenv("GADGET_TRANSLATION_BACKEND", "ollama")
    monkeypatch.setenv("OLLAMA_TRANSLATION_MODEL", "hf.co/tencent/Hy-MT2-1.8B-GGUF")
    # Pretend the server is up with the model pulled, so load() passes offline.
    monkeypatch.setattr(engine, "_ollama_tags",
                        lambda host, timeout=3: ["hf.co/tencent/Hy-MT2-1.8B-GGUF:latest"])

    proxy = engine.create_engine()
    assert isinstance(proxy._engine, engine.OllamaEngine)
    engine._engine_cache.clear()


def test_factory_auto_prefers_ollama_when_available(monkeypatch):
    engine._engine_cache.clear()
    monkeypatch.delenv("GADGET_TRANSLATION_BACKEND", raising=False)
    monkeypatch.delenv("GADGET_TRANSLATION_MODEL", raising=False)
    monkeypatch.setattr(engine, "_ollama_available", lambda model: True)
    monkeypatch.setattr(engine, "_ollama_tags",
                        lambda host, timeout=3: ["hf.co/tencent/Hy-MT2-1.8B-GGUF:latest"])

    proxy = engine.create_engine()
    assert isinstance(proxy._engine, engine.OllamaEngine)
    engine._engine_cache.clear()


def test_factory_auto_skips_ollama_for_overridden_model(monkeypatch):
    """A custom model (not the default) must NOT be silently routed to ollama's
    default tag — it falls through to an in-process backend that honors it."""
    engine._engine_cache.clear()
    monkeypatch.delenv("GADGET_TRANSLATION_BACKEND", raising=False)
    monkeypatch.setenv("GADGET_TRANSLATION_MODEL", "some-org/custom-translator")
    monkeypatch.setattr(engine, "_ollama_available", lambda model: True)  # ollama IS up
    monkeypatch.setattr(engine, "_vllm_available", lambda: False)
    monkeypatch.setattr(engine, "_llamacpp_available", lambda: True)
    monkeypatch.setattr(engine.LlamaCppEngine, "load", lambda self: None)
    monkeypatch.setattr(engine, "_free_ollama_vram", lambda: None)

    proxy = engine.create_engine()
    assert not isinstance(proxy._engine, engine.OllamaEngine)
    assert isinstance(proxy._engine, engine.LlamaCppEngine)
    engine._engine_cache.clear()


def test_cache_keyed_by_backend(monkeypatch):
    """Same model under two backends must yield two distinct engines — the old
    model-id-only key silently returned the first backend's engine for the second."""
    engine._engine_cache.clear()
    monkeypatch.setattr(engine.OllamaEngine, "load", lambda self: None)
    monkeypatch.setattr(engine.LlamaCppEngine, "load", lambda self: None)
    monkeypatch.setattr(engine, "_free_ollama_vram", lambda: None)

    monkeypatch.setenv("GADGET_TRANSLATION_BACKEND", "ollama")
    a = engine.create_engine()._engine
    monkeypatch.setenv("GADGET_TRANSLATION_BACKEND", "llamacpp")
    b = engine.create_engine()._engine

    assert isinstance(a, engine.OllamaEngine)
    assert isinstance(b, engine.LlamaCppEngine)
    assert a is not b
    engine._engine_cache.clear()


def test_keep_ollama_skips_eviction(monkeypatch):
    """GADGET_KEEP_OLLAMA short-circuits _free_ollama_vram before any network probe."""
    def boom(*a, **k):
        raise AssertionError("must not probe Ollama when GADGET_KEEP_OLLAMA is set")

    monkeypatch.setenv("GADGET_KEEP_OLLAMA", "1")
    monkeypatch.setattr("urllib.request.urlopen", boom)
    engine._free_ollama_vram()  # returns early, no urlopen


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
