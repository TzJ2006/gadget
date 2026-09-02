"""Characterization test — summarize.parsers._extract_codex_project (cconboard Phase 5 gate).

Locks current behavior of _extract_codex_project BEFORE the OB-515 cleanup
(removing the redundant in-function `import re as _re`; module top already imports re).
The <cwd>-regex paths (the ones using the redundant import) are covered explicitly.

Run: conda run -n AI python -m pytest .devcompanion/tests/char/test_char_parsers.py -q
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from summarize.parsers import _extract_codex_project   # noqa: E402


class TestExtractCodexProject:
    def test_session_meta_cwd_wins(self):
        lines = [{"type": "session_meta", "payload": {"cwd": "/home/user/myproj"}}]
        assert _extract_codex_project(lines) == "myproj"

    def test_message_block_cwd_tag(self):
        # exercises the regex path at line ~374 (redundant `import re as _re`)
        lines = [{"payload": {"type": "message",
                              "content": [{"text": "intro <cwd>/a/b/proj2</cwd> tail"}]}}]
        assert _extract_codex_project(lines) == "proj2"

    def test_user_message_cwd_tag(self):
        # exercises the regex path at line ~384 (redundant `import re as _re`)
        lines = [{"role": "user", "type": "message",
                  "content": [{"text": "<cwd>/x/y/proj3</cwd>"}]}]
        assert _extract_codex_project(lines) == "proj3"

    def test_session_meta_precedence_over_cwd_tag(self):
        lines = [
            {"role": "user", "type": "message",
             "content": [{"text": "<cwd>/x/y/proj3</cwd>"}]},
            {"type": "session_meta", "payload": {"cwd": "/home/user/winner"}},
        ]
        assert _extract_codex_project(lines) == "winner"

    def test_no_match_returns_unknown(self):
        assert _extract_codex_project([{"type": "other"}]) == "unknown"

    def test_empty_returns_unknown(self):
        assert _extract_codex_project([]) == "unknown"
