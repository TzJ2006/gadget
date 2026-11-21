"""LLM-error repair skip and OpenReview venue memo / fuzzy-match pruning (mock-only)."""

import difflib
from unittest.mock import MagicMock, patch

from research.apis import openreview_client as orc
from research.scout import evaluate


def test_llm_call_error_skips_json_repair():
    with patch.object(evaluate, "call_llm", side_effect=TimeoutError("timed out")), \
         patch.object(evaluate, "_common_try_repair_result") as repair:
        result = evaluate.call_scout_llm("ollama", "prompt", timeout=5)
        assert result["parse_error"] is True and result["raw_response"] == "timed out"
        assert evaluate._try_repair_result(result, "ollama", 5) is result
        assert "llm_error" not in result
        repair.assert_not_called()
    # Unparseable model output still goes to repair.
    with patch.object(evaluate, "_common_try_repair_result", return_value={"ok": 1}) as repair:
        assert evaluate._try_repair_result({"parse_error": True, "raw_response": "x"}, "ollama", 5) == {"ok": 1}
        repair.assert_called_once()


def _bare_client():
    client = object.__new__(orc.OpenReviewClient)
    client._cache = None
    client._venue_memo = {}
    client._client = MagicMock()
    return client


def test_venue_submissions_fetched_once_per_client():
    client = _bare_client()
    client._client.get_all_notes.return_value = []
    with patch.object(orc.openreview_limiter, "acquire"):
        assert client._get_venue_submissions("ICLR.cc/2025/Conference", "k") == []
        assert client._get_venue_submissions("ICLR.cc/2025/Conference", "k") == []
    client._client.get_all_notes.assert_called_once()


def _reference_fuzzy(query, submissions):
    nq = orc._normalize_title(query)
    best, best_ratio = None, 0.0
    for sub in submissions:
        r = difflib.SequenceMatcher(None, nq, orc._normalize_title(sub.get("title", ""))).ratio()
        if r > best_ratio:
            best_ratio, best = r, sub
    return best if best and best_ratio >= 0.85 else None


def test_fuzzy_match_pruning_matches_full_scan():
    subs = [{"title": t} for t in [
        "Attention Is All You Need",
        "Attention is all you need!",          # tie with first -> first wins
        "Attention Is All You Need Too",
        "Deep Residual Learning for Image Recognition",
        "",
        "Completely unrelated",
    ]]
    client = _bare_client()
    for q in ["Attention is all you need", "Attention Is All You Need Too.",
              "deep residual learning for image recognition", "nothing like it"]:
        assert client._fuzzy_match_title(q, subs) is _reference_fuzzy(q, subs)
