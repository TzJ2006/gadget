"""Output overflow adds a compacting merge round; broken chunk JSON is regenerated."""
import pytest

from common import llm
from common.ollama_chat import LLMOutputTruncated

PARTS = [{"summary": str(i) + "x" * 250} for i in range(4)]


def _merge():
    return llm.hierarchical_merge(
        "ollama", PARTS, "merge:", lambda text: llm.LLMCallConfig(prompt=text),
        60, max_chars=100_000)


def test_output_overflow_adds_one_compacting_round(monkeypatch):
    calls = []

    def fake(api, config):
        calls.append(config.anthropic_tool_name)
        if len(calls) == 1:
            raise LLMOutputTruncated("length")
        return {"summary": "ok", "facts": []}

    monkeypatch.setattr(llm, "call_llm", fake)
    assert _merge() == {"summary": "ok", "facts": []}
    # overflow, then >=2 compacting groups, then the final merge
    assert calls.count("submit_notes") >= 2 and len(calls) >= 4


def test_second_overflow_is_raised_not_looped(monkeypatch):
    def fake(api, config):
        if config.anthropic_tool_name == "submit_notes":
            return {"summary": "n", "facts": []}
        raise LLMOutputTruncated("length")

    monkeypatch.setattr(llm, "call_llm", fake)
    with pytest.raises(LLMOutputTruncated):
        _merge()


def test_chunk_with_unrepairable_json_is_regenerated(monkeypatch):
    results = iter([{"parse_error": True, "raw_response": "{bad"}, {"summary": "good"}])
    monkeypatch.setattr(llm, "call_llm", lambda api, config: next(results))
    monkeypatch.setattr(llm, "try_repair_result", lambda r, api, t: r)
    out = llm.timed_llm_call("ollama", llm.LLMCallConfig(prompt="p", timeout=60), 1, 1)
    assert out == {"summary": "good"}


def test_chunk_text_splits_a_single_oversized_text():
    from common.llm import chunk_text
    big = "\n".join("x" * 9 for _ in range(100))  # 999 chars
    chunks = chunk_text(["a", big], max_chars=100)
    assert all(sum(map(len, c)) <= 100 for c in chunks)
    assert "".join("".join(c) for c in chunks) == "a" + big
