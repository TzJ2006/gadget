"""Structured Ollama calls must not inherit the OpenAI default model."""

from contextlib import nullcontext
from common import ollama_chat

import pytest

from common import llm


@pytest.mark.parametrize("override", [None, "local-custom:7b"])
@pytest.mark.parametrize("explicit", ["", "explicit:8b"])
def test_structured_ollama_uses_local_model(monkeypatch, override, explicit):
    monkeypatch.delenv("GADGET_LLM_ROUTE", raising=False)
    monkeypatch.delenv("LC_LLM_ROUTE", raising=False)
    monkeypatch.setenv("OPENAI_MODEL", "cloud-model")
    if override:
        monkeypatch.setenv("OLLAMA_MODEL", override)
    else:
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    admitted = []
    monkeypatch.setattr(llm, "_admit_ollama_text", lambda model:
                        (admitted.append(model) or nullcontext(), RuntimeError))
    monkeypatch.setattr(llm, "_ollama_client", lambda: object())
    monkeypatch.setattr(llm, "_chat_json", lambda client, model, config, **kwargs:
                        {"model": model})

    monkeypatch.setattr(ollama_chat, "complete", lambda endpoint, model, *a, **kw:
                        ollama_chat.LLMResult('{"model":"' + model + '"}', "test", model))
    result = llm.call_ollama(llm.LLMCallConfig(prompt="test", ollama_model=explicit))

    expected = explicit or override or llm.DEFAULT_OLLAMA_CHAT_MODEL
    assert admitted == [expected]
    assert result == {"model": expected}


def test_structured_openai_keeps_its_default(monkeypatch):
    monkeypatch.delenv("GADGET_LLM_ROUTE", raising=False)
    monkeypatch.delenv("LC_LLM_ROUTE", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setattr(llm, "_openai_client", lambda: object())
    monkeypatch.setattr(llm, "_chat_json", lambda client, model, config:
                        {"model": model})
    assert llm.call_openai(llm.LLMCallConfig(prompt="test")) == {"model": "gpt-4o"}
