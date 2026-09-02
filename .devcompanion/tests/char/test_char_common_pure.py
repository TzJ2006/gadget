"""Characterization tests — common/ pure functions (cconboard Phase 3).

These lock the CURRENT behavior of pure utility functions BEFORE any onboarding
modification. Named test_*.py so default pytest collects them (the legacy
.devcompanion/tests/*.test.py skeletons are NOT collected by pytest and contain
only `assert False` stubs).

Run: conda run -n AI python -m pytest .devcompanion/tests/char/ -q
"""
import sys
from pathlib import Path

# Make repo root importable (so `import common.*` works regardless of cwd)
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.io import content_hash, load_json_config           # noqa: E402
from common.json_utils import (                                 # noqa: E402
    try_parse_json, parse_json_response, _fix_unescaped_quotes,
)


# ── common/io.py :: content_hash ─────────────────────────────────────
class TestContentHash:
    def test_known_value_hello(self):
        # SHA-256("hello")[:16]
        assert content_hash("hello") == "2cf24dba5fb0a30e"

    def test_known_value_empty(self):
        assert content_hash("") == "e3b0c44298fc1c14"

    def test_default_length_is_16(self):
        assert len(content_hash("anything")) == 16

    def test_custom_length(self):
        assert content_hash("abc", length=8) == "ba7816bf"
        assert content_hash("abc", length=64) == \
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"

    def test_deterministic(self):
        assert content_hash("repeat") == content_hash("repeat")


# ── common/io.py :: load_json_config ─────────────────────────────────
class TestLoadJsonConfig:
    def test_missing_file_returns_empty(self, tmp_path):
        assert load_json_config(tmp_path / "nope.json") == {}

    def test_valid_file(self, tmp_path):
        p = tmp_path / "c.json"
        p.write_text('{"a": 1, "b": [2, 3]}', encoding="utf-8")
        assert load_json_config(p) == {"a": 1, "b": [2, 3]}

    def test_malformed_returns_empty(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{not valid json", encoding="utf-8")
        assert load_json_config(p) == {}

    def test_cache_memoizes(self, tmp_path):
        p = tmp_path / "c.json"
        p.write_text('{"x": 1}', encoding="utf-8")
        cache = {}
        first = load_json_config(p, cache=cache)
        p.write_text('{"x": 999}', encoding="utf-8")  # change on disk
        second = load_json_config(p, cache=cache)      # served from cache
        assert first == second == {"x": 1}


# ── common/json_utils.py :: try_parse_json ───────────────────────────
class TestTryParseJson:
    def test_direct_object(self):
        assert try_parse_json('{"k": 1}') == {"k": 1}

    def test_strips_whitespace(self):
        assert try_parse_json('   {"k": 1}\n ') == {"k": 1}

    def test_markdown_code_block(self):
        assert try_parse_json('```json\n{"k": 2}\n```') == {"k": 2}

    def test_prefers_largest_valid_block(self):
        text = '```\n{"a": 1}\n```\nnoise\n```json\n{"a": 1, "b": 2}\n```'
        assert try_parse_json(text) == {"a": 1, "b": 2}

    def test_embedded_object_with_surrounding_prose(self):
        text = 'Here is the result: {"answer": 42} — done.'
        assert try_parse_json(text) == {"answer": 42}

    def test_garbage_returns_none(self):
        assert try_parse_json("not json at all") is None

    def test_nested_depth_matching(self):
        text = 'prefix {"a": {"b": {"c": 1}}} suffix'
        assert try_parse_json(text) == {"a": {"b": {"c": 1}}}


# ── common/json_utils.py :: parse_json_response ──────────────────────
class TestParseJsonResponse:
    def test_valid_passthrough(self):
        assert parse_json_response('{"ok": true}') == {"ok": True}

    def test_failure_returns_error_dict(self):
        result = parse_json_response("totally not json")
        assert result.get("parse_error") == "Cannot extract JSON"
        assert result.get("raw_response") == "totally not json"

    def test_recovers_unescaped_quotes(self):
        # inner unescaped quotes inside a string value get repaired
        text = '{"msg": "she said "hi" to me"}'
        result = parse_json_response(text)
        assert result.get("msg") == 'she said "hi" to me'


# ── common/json_utils.py :: _fix_unescaped_quotes ────────────────────
class TestFixUnescapedQuotes:
    def test_escapes_inner_quotes(self):
        fixed = _fix_unescaped_quotes('{"a": "x "y" z"}')
        assert fixed == '{"a": "x \\"y\\" z"}'

    def test_leaves_structural_quotes_untouched(self):
        s = '{"a": "b"}'
        assert _fix_unescaped_quotes(s) == s
