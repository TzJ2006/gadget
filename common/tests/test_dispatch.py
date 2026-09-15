"""Backend dispatch validation — unknown backends must fail loudly, not silently
degrade to some other backend / auto-select (Phase 2).

The stub loop below is deliberately driven by LLM_BACKENDS rather than a literal
list: it is what catches a backend declared but not wired, or wired but not
declared. Removing claude_cli was one line in llm.py and this kept passing.
"""

import pytest

import common.engine as engine
import common.llm as llm
from common.llm import call_llm, call_llm_raw, LLMCallConfig, LLM_BACKENDS


def test_call_llm_raw_rejects_unknown_backend():
    with pytest.raises(ValueError, match="Unknown LLM backend"):
        call_llm_raw("hi", backend="anthropci")  # typo → must raise, not silently route


def test_call_llm_rejects_unknown_backend():
    with pytest.raises(ValueError, match="Unknown LLM backend"):
        call_llm("bogus", LLMCallConfig(prompt="hi"))


def test_valid_backends_still_dispatch(monkeypatch):
    # every declared backend must route to a real branch, never the ValueError.
    # Stub each raw impl so no network/subprocess is touched (repo test convention).
    for b in LLM_BACKENDS:
        impl = f"_raw_{b}"
        assert hasattr(llm, impl), f"{b} is declared but has no {impl}"
        monkeypatch.setattr(llm, impl, lambda *a, **k: "ok")
    for b in LLM_BACKENDS:
        assert call_llm_raw("hi", backend=b) == "ok"


def test_create_engine_rejects_unknown_translation_backend(monkeypatch):
    monkeypatch.setattr(engine, "_engine_cache", {})  # force cache miss
    monkeypatch.setenv("GADGET_TRANSLATION_BACKEND", "llama_cpp")  # not "llamacpp"
    with pytest.raises(ValueError, match="Unknown GADGET_TRANSLATION_BACKEND"):
        engine.create_engine()
