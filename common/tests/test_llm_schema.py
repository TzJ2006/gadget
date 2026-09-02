"""Schema-constrained decoding on the local Ollama path — mocked, no server.

Plain ``json_object`` only guarantees *valid* JSON, not the right shape: qwen3.8
returned ``daily_overview``'s contents as the whole daily report on roughly half
of real merge calls, silently emptying tasks/problems/learnings. ``call_ollama``
therefore reuses the caller's Anthropic tool schema to constrain decoding.
"""

import json

import common.llm as llm
from common.llm import LLMCallConfig, call_ollama, call_openai


SCHEMA = {
    "type": "object",
    "properties": {"summary": {"type": "string"}, "tasks": {"type": "array"},
                   "learnings": {"type": "array"}},
    "required": ["summary"],          # `tasks`/`learnings` optional for tool use
}
CONSTRAINED = {**SCHEMA, "required": ["summary", "tasks", "learnings"]}
TOOLS = [{"name": "submit_report", "input_schema": SCHEMA}]


class _FakeClient:
    """Records the create() kwargs and replies with a minimal valid report."""

    def __init__(self):
        self.seen = {}
        self.chat = self

    @property
    def completions(self):
        return self

    def create(self, **kwargs):
        self.seen = kwargs
        payload = json.dumps({"summary": "s", "tasks": []})
        return type("R", (), {
            "choices": [type("C", (), {"message": type("M", (), {"content": payload})()})()],
            "usage": None,
        })()


def _patch(monkeypatch, factory_name):
    fake = _FakeClient()
    monkeypatch.setattr(llm, factory_name, lambda: fake)
    return fake


def test_ollama_constrains_decoding_with_the_tool_schema(monkeypatch):
    fake = _patch(monkeypatch, "_ollama_client")
    out = call_ollama(LLMCallConfig(prompt="p", anthropic_tools=TOOLS,
                                    anthropic_tool_name="submit_report"))
    assert out == {"summary": "s", "tasks": []}
    rf = fake.seen["response_format"]
    assert rf["type"] == "json_schema"
    # every top-level property required, else the model emits a minimal stub
    assert rf["json_schema"]["schema"] == CONSTRAINED


def test_ollama_without_tools_falls_back_to_json_object(monkeypatch):
    fake = _patch(monkeypatch, "_ollama_client")
    call_ollama(LLMCallConfig(prompt="p"))
    assert fake.seen["response_format"] == {"type": "json_object"}


def test_openai_stays_on_json_object(monkeypatch):
    """Cloud json_schema is strict-only and would reject these schemas
    (no additionalProperties:false, partial required)."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    fake = _patch(monkeypatch, "_openai_client")
    call_openai(LLMCallConfig(prompt="p", anthropic_tools=TOOLS))
    assert fake.seen["response_format"] == {"type": "json_object"}


def test_schema_from_tools_ignores_malformed_entries():
    assert llm._schema_from_tools(None) is None
    assert llm._schema_from_tools([]) is None
    assert llm._schema_from_tools([{"name": "x"}]) is None          # no input_schema
    assert llm._schema_from_tools([{"input_schema": "nope"}]) is None  # not a dict
    assert llm._schema_from_tools(TOOLS) == CONSTRAINED
    # nothing to promote -> schema passed through untouched, not corrupted
    bare = {"type": "object"}
    assert llm._schema_from_tools([{"input_schema": bare}]) == bare


def test_promoting_required_does_not_mutate_the_callers_schema():
    """The tool schema is reused for the Anthropic path, where these fields are
    genuinely optional — promotion must copy, not edit in place."""
    tools = [{"input_schema": dict(SCHEMA)}]
    llm._schema_from_tools(tools)
    assert tools[0]["input_schema"]["required"] == ["summary"]
