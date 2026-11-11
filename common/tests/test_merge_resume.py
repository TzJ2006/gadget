"""Resume only completed intermediate merges; model calls are fully mocked."""
import json

import pytest

from common import llm


PARTS = [{"summary": str(i) + "x" * 250} for i in range(4)]


def merge(cache_dir, *, context="source-v1", prompt="merge:", model="test:7b", timeout=60):
    return llm.hierarchical_merge(
        "ollama", PARTS, prompt,
        lambda text: llm.LLMCallConfig(prompt=text, ollama_model=model),
        timeout, max_chars=400, cache_dir=cache_dir, cache_context=context)


def test_timeout_resumes_completed_groups_but_final_answer_stays_fresh(tmp_path, monkeypatch):
    calls = []

    def fail_third(api, config):
        calls.append(config.prompt)
        if len(calls) == 3:
            raise TimeoutError("budget exhausted")
        return {"summary": "small"}

    monkeypatch.setattr(llm, "call_llm", fail_third)
    with pytest.raises(TimeoutError):
        merge(tmp_path)
    assert len(list(tmp_path.glob("*.json"))) == 2
    completed = calls[:2]
    calls.clear()

    def succeed(api, config):
        calls.append(config.prompt)
        return {"summary": "small"}

    monkeypatch.setattr(llm, "call_llm", succeed)
    assert merge(tmp_path, timeout=120) == {"summary": "small"}
    assert len(calls) == 3  # Two unfinished groups, then the final answer.
    assert not any(prompt in calls for prompt in completed)
    calls.clear()
    merge(tmp_path)
    assert len(calls) == 1  # Validation retries must generate a fresh final answer.


@pytest.mark.parametrize("change", ["context", "prompt", "model", "request_model", "endpoint"])
def test_cache_does_not_cross_source_prompt_or_model_routes(tmp_path, monkeypatch, change):
    calls = []
    monkeypatch.setattr(llm, "call_llm", lambda api, config:
                        calls.append(config.prompt) or {"summary": "small"})
    merge(tmp_path)
    assert len(calls) == 5
    calls.clear()
    kwargs = {}
    if change == "endpoint":
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:19999")
    elif change != "request_model":
        kwargs[change] = "changed"
    with llm.total_budget(60, model="changed" if change == "request_model" else None):
        merge(tmp_path, **kwargs)
    assert len(calls) == 5


def test_disabled_cache_does_not_reuse_intermediates(monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "call_llm", lambda api, config:
                        calls.append(config.prompt) or {"summary": "small"})
    merge(None)
    merge(None)
    assert len(calls) == 10


def test_json_whitespace_does_not_force_single_report_merge_groups(monkeypatch):
    parts = [{"summary": name, "facts": [{"value": '内容 "quoted"\nline', "id": i}
                                       for i in range(6)]} for name in ("first", "second")]
    compact = [json.dumps(p, ensure_ascii=False, separators=(",", ":")) for p in parts]
    budget = sum(map(len, compact)) + 100
    assert sum(len(json.dumps(p, ensure_ascii=False, indent=2)) for p in parts) > budget
    calls = []
    monkeypatch.setattr(llm, "call_llm", lambda api, config:
                        calls.append(config.prompt) or {"summary": "combined"})
    llm.hierarchical_merge("ollama", parts, "merge:", llm.LLMCallConfig, max_chars=budget)
    assert len(calls) == 1
    assert all(text in calls[0] for text in compact)
    assert [json.loads(text) for text in compact] == parts


def test_only_intermediate_merges_receive_a_smaller_output_budget(monkeypatch):
    budgets = []
    monkeypatch.setattr(llm, "call_llm", lambda api, config:
                        budgets.append(config.max_tokens) or {"summary": "small"})
    merge(None)
    assert budgets == [256, 256, 256, 256, 8192]


def test_intermediate_notes_do_not_replace_the_final_report_schema(monkeypatch):
    tools = [{"name": "submit_report", "input_schema": {"type": "object",
             "properties": {"summary": {"type": "string"}, "tasks": {"type": "array"}}}}]
    calls = []
    monkeypatch.setattr(llm, "call_llm", lambda api, config:
                        calls.append(config) or {"summary": "small", "facts": ["source: completed"]})
    llm.hierarchical_merge("ollama", PARTS, "merge:", lambda text:
        llm.LLMCallConfig(prompt=text, anthropic_tool_name="submit_report", anthropic_tools=tools),
        max_chars=400)
    assert len(calls) == 5
    assert all(c.anthropic_tool_name == "submit_notes" for c in calls[:-1])
    assert all("facts" in c.anthropic_tools[0]["input_schema"]["properties"] for c in calls[:-1])
    assert calls[-1].anthropic_tool_name == "submit_report"
    assert calls[-1].anthropic_tools == tools
    assert "source: completed" in calls[-1].prompt
