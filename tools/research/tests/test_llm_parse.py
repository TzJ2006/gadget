"""Profiler JSON parsing delegates repair to common.json_utils (Phase 3 dedup)."""

from unittest.mock import patch

from research import llm as profiler_llm


def test_clean_json_parses_without_repair():
    with patch.object(profiler_llm, "repair_json_with_llm") as repair:
        assert profiler_llm.parse_json_response('{"a": 1}') == {"a": 1}
        repair.assert_not_called()


def test_broken_json_delegates_to_common_repair():
    with patch.object(profiler_llm, "repair_json_with_llm", return_value={"a": 2}) as repair:
        assert profiler_llm.parse_json_response("not json {a:", backend="ollama") == {"a": 2}
        # delegated with escalating strategy, the profiler's larger cap, and the
        # old inline loop's 300s timeout (common's 120s default is a regression)
        _, kwargs = repair.call_args
        assert kwargs["strategy"] == "escalating" and kwargs["max_chars"] == 20000
        assert kwargs["timeout"] == 300


def test_parse_json_default_backend_is_ollama():
    with patch.object(profiler_llm, "repair_json_with_llm", return_value={"ok": 1}) as repair:
        assert profiler_llm.parse_json_response("not json") == {"ok": 1}
        assert repair.call_args[0][1] == "ollama"


def test_unrepairable_logs_and_returns_empty():
    with patch.object(profiler_llm, "repair_json_with_llm", return_value=None), \
         patch.object(profiler_llm, "_save_failed_response") as saved:
        assert profiler_llm.parse_json_response("garbage") == {}
        saved.assert_called_once()


def test_call_llm_forwards_to_raw():
    with patch.object(profiler_llm, "call_llm_raw", return_value="ok") as raw:
        assert profiler_llm.call_llm("hi", backend="ollama", timeout=600) == "ok"
        raw.assert_called_once_with("hi", backend="ollama", model="sonnet", timeout=600)
