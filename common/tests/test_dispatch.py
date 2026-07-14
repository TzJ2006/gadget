"""Backend dispatch validation — unknown backends must fail loudly, not silently
degrade to claude_cli / auto-select (Phase 2)."""

import pytest

import common.engine as engine
import common.llm as llm
from common.llm import call_llm, call_llm_raw, LLMCallConfig, LLM_BACKENDS


def test_call_llm_raw_rejects_unknown_backend():
    with pytest.raises(ValueError, match="Unknown LLM backend"):
        call_llm_raw("hi", backend="anthropci")  # typo → must raise, not hit claude_cli


def test_call_llm_rejects_unknown_backend():
    with pytest.raises(ValueError, match="Unknown LLM backend"):
        call_llm("bogus", LLMCallConfig(prompt="hi"))


def test_valid_backends_still_dispatch(monkeypatch):
    # every declared backend must route to a real branch, never the ValueError.
    # Stub each raw impl so no network/subprocess is touched (repo test convention).
    for name in ("_raw_anthropic", "_raw_openai", "_raw_ollama", "_raw_claude_cli"):
        monkeypatch.setattr(llm, name, lambda *a, **k: "ok")
    for b in LLM_BACKENDS:
        assert call_llm_raw("hi", backend=b) == "ok"


def test_create_engine_rejects_unknown_translation_backend(monkeypatch):
    monkeypatch.setattr(engine, "_engine_cache", {})  # force cache miss
    monkeypatch.setenv("GADGET_TRANSLATION_BACKEND", "llama_cpp")  # not "llamacpp"
    with pytest.raises(ValueError, match="Unknown GADGET_TRANSLATION_BACKEND"):
        engine.create_engine()
