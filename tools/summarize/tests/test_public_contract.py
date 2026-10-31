import io
import json
from contextlib import redirect_stdout
from types import SimpleNamespace

import pytest
from summarize import public_api, auto
from summarize.summarizer import chunk_conversations, format_conversations
from common import llm


def test_stdout_is_only_json_even_when_engine_prints(monkeypatch, capsys):
    def generate(*args, **kwargs):
        print("diagnostic progress")
        return {"summary": "result"}
    monkeypatch.setattr(public_api, "summarize_daily", generate)
    monkeypatch.setattr(public_api.sys, "stdin", io.StringIO(json.dumps({"op": "daily", "day": "2026-10-21",
        "conversations": [{"messages": [{"role": "user", "content": "test"}]}]})))
    assert public_api.main([]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == {"summary": "result"}
    assert "diagnostic progress" in captured.err


def test_save_report_reuses_identical_inputs_and_updates_changed_inputs(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(public_api, "summarize_daily", lambda *a, **k: calls.append(a) or {"summary": "ok"})
    payload = {"op": "daily", "day": "2026-10-21", "save_dir": str(tmp_path),
               "conversations": [{"messages": [{"role": "user", "content": "one"}]}]}
    public_api.dispatch(payload)
    public_api.dispatch(payload)
    assert len(calls) == 1
    payload["conversations"][0]["messages"][0]["content"] = "two"
    public_api.dispatch(payload)
    assert len(calls) == 2
    public_api.dispatch({**payload, "force": True})
    assert len(calls) == 3
    assert json.loads((tmp_path / "2026-10-21.json").read_text())["summary"] == "ok"


def test_large_message_is_lossless_and_bounded():
    text = "".join(f"unique-{n:05d}," for n in range(2000))
    conversation = {"source": "generic", "project": "p", "timestamp": "", "messages": [{"role": "user", "content": text}]}
    chunks = chunk_conversations([conversation], 2000)
    assert len(chunks) > 1
    assert all(len(format_conversations(chunk)) <= 2000 for chunk in chunks)
    assert "".join(m["content"] for c in chunks for conv in c for m in conv["messages"]) == text


def test_total_budget_covers_retries_and_model_override(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(llm.time, "monotonic", lambda: clock[0])
    seen = []
    monkeypatch.setattr(llm, "call_openai", lambda cfg: seen.append(cfg) or {"summary": "ok"})
    monkeypatch.setattr(llm, "_refuse_cloud_route", lambda api: None)
    with llm.total_budget(5, model="explicit-model"):
        clock[0] += 4
        llm.call_llm("openai", llm.LLMCallConfig(prompt="x", timeout=600))
        assert seen[0].timeout == 1 and seen[0].openai_model == "explicit-model"
        clock[0] += 2
        with pytest.raises(TimeoutError):
            llm.call_llm("openai", llm.LLMCallConfig(prompt="x"))
    assert len(seen) == 1


def test_auto_stops_before_downstream_steps_when_export_fails(monkeypatch):
    calls = []
    monkeypatch.setattr(auto.subprocess, "run", lambda cmd, **kw: calls.append(cmd) or SimpleNamespace(returncode=7))
    args = SimpleNamespace(date=None, skip_onboard_check=True, api="ollama", deploy=False,
                           force=False, workers=1, no_ssh=True)
    with pytest.raises(SystemExit) as error:
        auto.cmd_auto(args)
    assert error.value.code == 7
    assert len(calls) == 1 and calls[0][3:5] == ["daily", "export"]


def test_period_input_keeps_pending_conversation_facts():
    from summarize.monthly_summary import format_reports_for_llm
    report = {"date": "2026-10-21", "summary": "Engine reused", "_generation_hash": "cache-id",
              "token_usage": {"total": 99},
              "conversation_summaries": [{"summary": "Microphone test pending. Nothing published."}]}
    text = format_reports_for_llm([report])
    assert "Microphone test pending. Nothing published." in text
    assert "token_usage" not in text and "cache-id" not in text
    assert "_generation_hash" in report
