"""Publish orchestrator: preflight exit-code routing, and when the stamp moves.

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


def test_an_abort_still_records_that_the_media_was_compressed(monkeypatch):
    """The stamp is the compression boundary, not a "we shipped" marker.

    It used to move only after a successful push, which reads naturally from
    the name .last_build — but compression is lossy, so every preflight abort
    left the images looking unmodified-since and the next run quantized them
    all over again, one notch worse each time. The work it records did happen,
    so it is recorded. (This assertion is the inverse of what this test file
    pinned before; the change is deliberate.)
    """
    called = _stub_steps(monkeypatch, preflight_rc=1)
    assert pub.main() == 1
    assert "stamp" in called, "an aborted run will re-compress everything"


def test_main_continues_on_preflight_exit_2(monkeypatch):
    called = _stub_steps(monkeypatch, preflight_rc=2)
    assert pub.main() == 0
    assert called == [
        "translate", "rewrite", "img", "vid", "stamp", "clean", "hugo", "push",
    ]
