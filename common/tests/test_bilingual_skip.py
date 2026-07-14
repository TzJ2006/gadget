"""write_bilingual re-run economics: unchanged source must not re-translate.

The translated file carries a `gadget:src-hash` marker; a second call with
byte-identical source returns the staged paths without touching the engine.
"""

from pathlib import Path

import pytest

import common.bilingual as bilingual


class Eng:
    """sanitize_frontmatter_language may call this; the test content has no
    summary/description fields, so it never should."""

    def generate_batch(self, prompts, **kw):
        raise AssertionError("engine must not be called by these tests")

    def load(self):
        pass

    def unload(self):
        pass


CONTENT = "---\ntitle: t\n---\n\nHello world, a plain English body.\n"


def _fake_translate(calls):
    def fake(content, src, tgt, engine=None, pbar=None):
        calls.append((src, tgt))
        return "---\ntitle: t\n---\n\n翻译正文。\n"
    return fake


def test_skip_when_source_unchanged(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(bilingual, "translate_markdown_document", _fake_translate(calls))
    site = tmp_path / "website"
    site.mkdir()
    rel = Path("bugJournal/daily/2026-07-03.md")

    en1, zh1 = bilingual.write_bilingual(site, rel, CONTENT, engine=Eng())
    assert len(calls) == 1 and zh1 is not None
    # marker stamped in BOTH files — the skip requires both to match
    assert "gadget:src-hash:" in zh1.read_text(encoding="utf-8")
    assert "gadget:src-hash:" in en1.read_text(encoding="utf-8")

    en2, zh2 = bilingual.write_bilingual(site, rel, CONTENT, engine=Eng())
    assert len(calls) == 1                      # skipped — no second translation
    assert (en2, zh2) == (en1, zh1)


def test_retranslates_when_source_changes(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(bilingual, "translate_markdown_document", _fake_translate(calls))
    site = tmp_path / "website"
    site.mkdir()
    rel = Path("bugJournal/daily/2026-07-03.md")

    bilingual.write_bilingual(site, rel, CONTENT, engine=Eng())
    bilingual.write_bilingual(site, rel, CONTENT + "\nAppended line.\n", engine=Eng())
    assert len(calls) == 2                      # changed source → re-translated


def test_failed_translation_leaves_no_marker_so_next_run_retries(tmp_path, monkeypatch):
    calls: list = []

    def fail_then_succeed(content, src, tgt, engine=None, pbar=None):
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("garbage output")
        return "---\ntitle: t\n---\n\n翻译正文。\n"

    monkeypatch.setattr(bilingual, "translate_markdown_document", fail_then_succeed)
    site = tmp_path / "website"
    site.mkdir()
    rel = Path("posts/x.md")

    en1, zh1 = bilingual.write_bilingual(site, rel, CONTENT, engine=Eng())
    assert zh1 is None                          # first attempt failed
    en2, zh2 = bilingual.write_bilingual(site, rel, CONTENT, engine=Eng())
    assert len(calls) == 2 and zh2 is not None  # retried, not skipped


def test_content_flipflop_around_failure_never_serves_stale_original(tmp_path, monkeypatch):
    """A -> B(translation fails) -> A must NOT skip on the third run: the staged
    original still holds B, so serving the old A translation pair would publish
    a stale original. The both-files marker check forces a re-run."""
    calls: list = []

    def translate(content, src, tgt, engine=None, pbar=None):
        calls.append(1)
        if len(calls) == 2:
            raise ValueError("garbage output")
        return "---\ntitle: t\n---\n\n翻译正文。\n"

    monkeypatch.setattr(bilingual, "translate_markdown_document", translate)
    site = tmp_path / "website"
    site.mkdir()
    rel = Path("posts/y.md")
    content_b = CONTENT + "\nDifferent body.\n"

    bilingual.write_bilingual(site, rel, CONTENT, engine=Eng())      # A ok
    bilingual.write_bilingual(site, rel, content_b, engine=Eng())    # B fails
    en3, zh3 = bilingual.write_bilingual(site, rel, CONTENT, engine=Eng())  # A again
    assert len(calls) == 3                       # NOT skipped
    assert zh3 is not None
    assert "Hello world" in en3.read_text(encoding="utf-8")          # original is A


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
