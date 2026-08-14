"""Publish orchestrator: abort on preflight exit 1, continue on exit 2.

Run: ``python -m pytest tools/website/tests/test_publish.py -q``
"""

from __future__ import annotations

import subprocess

import publish as pub


def _stub_steps(monkeypatch, preflight_rc: int) -> list[str]:
    """Keep main() off the live site tree: no chdir, hugo, git, or timestamp."""
    called: list[str] = []

    class Stamp:
        def touch(self, *args, **kwargs):
            called.append("stamp")

    monkeypatch.setattr(pub.os, "chdir", lambda _p: None)
    monkeypatch.setattr(pub, "get_site_base_url", lambda _p: "https://example.test")
    monkeypatch.setattr(pub, "ensure_timestamp", lambda _p: 0.0)
    monkeypatch.setattr(
        pub, "invoke_translation_phase", lambda *_a, **_k: called.append("translate")
    )
    monkeypatch.setattr(
        pub, "rewrite_modified_markdown", lambda *_a, **_k: called.append("rewrite")
    )
    monkeypatch.setattr(pub, "compress_images", lambda *_a: called.append("img"))
    monkeypatch.setattr(pub, "compress_videos", lambda *_a: called.append("vid"))
    monkeypatch.setattr(pub, "run_preflight", lambda: preflight_rc)
    monkeypatch.setattr(pub, "clean_public", lambda: called.append("clean"))
    monkeypatch.setattr(pub, "run_hugo", lambda: called.append("hugo"))
    monkeypatch.setattr(pub, "commit_and_push", lambda: called.append("push"))
    monkeypatch.setattr(pub, "TIMESTAMP_FILE", Stamp())
    return called


def test_run_preflight_returns_subprocess_code(monkeypatch):
    def fake_run(cmd, *args, **kwargs):
        assert "preflight_check.py" in str(cmd)
        return subprocess.CompletedProcess(cmd, 2)

    monkeypatch.setattr(pub.subprocess, "run", fake_run)
    assert pub.run_preflight() == 2


def test_main_aborts_on_preflight_exit_1(monkeypatch):
    called = _stub_steps(monkeypatch, preflight_rc=1)
    assert pub.main() == 1
    assert "hugo" not in called
    assert "push" not in called
    assert "stamp" not in called


def test_main_continues_on_preflight_exit_2(monkeypatch):
    called = _stub_steps(monkeypatch, preflight_rc=2)
    assert pub.main() == 0
    assert called == [
        "translate", "rewrite", "img", "vid", "clean", "hugo", "push", "stamp",
    ]
