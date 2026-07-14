"""Profiler JSON parsing delegates repair to common.json_utils (Phase 3 dedup)."""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import llm as profiler_llm  # research/llm.py


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


def test_unrepairable_logs_and_returns_empty():
    with patch.object(profiler_llm, "repair_json_with_llm", return_value=None), \
         patch.object(profiler_llm, "_save_failed_response") as saved:
        assert profiler_llm.parse_json_response("garbage") == {}
        saved.assert_called_once()
