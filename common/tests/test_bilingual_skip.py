"""write_bilingual re-run economics: unchanged source must not re-translate.

The translated file carries a `gadget:src-hash` marker; a second call with
byte-identical source returns the staged paths without touching the engine.

Failed translations retry TRANSLATION_RETRIES times, then skip writing the
target language page (zh→en never copies Chinese into the English `.md`).
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
ZH_CONTENT = "---\ntitle: 标题\n---\n\n这是一段中文正文，用来测试中译英失败不会写入英文页。\n"
EN_FROM_ZH = "---\ntitle: Title\n---\n\nThis is the English translation of the body.\n"


@pytest.fixture(autouse=True)
def _isolate_failure_log(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    monkeypatch.setattr(bilingual, "LOGS_DIR", log_dir)
    return log_dir


def _fake_translate(calls, result="---\ntitle: t\n---\n\n翻译正文。\n"):
    def fake(content, src, tgt, engine=None, pbar=None):
        calls.append((src, tgt))
        return result
    return fake


def _fail_until(calls, succeed_after, result="---\ntitle: t\n---\n\n翻译正文。\n"):
    """Fail with ValueError until *succeed_after* calls, then return *result*.

    *succeed_after* is inclusive of that call index (1-based). Pass a number
    larger than any expected call count to fail forever.
    """
    def fake(content, src, tgt, engine=None, pbar=None):
        calls.append((src, tgt))
        if len(calls) < succeed_after:
            raise ValueError("garbage output")
        return result
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
    assert "gadget:src-hash:v2:" in en1.read_text(encoding="utf-8")

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
    n = bilingual.TRANSLATION_RETRIES
    monkeypatch.setattr(
        bilingual, "translate_markdown_document",
        _fail_until(calls, succeed_after=n + 1),
    )
    site = tmp_path / "website"
    site.mkdir()
    rel = Path("posts/x.md")

    en1, zh1 = bilingual.write_bilingual(site, rel, CONTENT, engine=Eng())
    assert zh1 is None                          # first write exhausted retries
    assert len(calls) == n
    en2, zh2 = bilingual.write_bilingual(site, rel, CONTENT, engine=Eng())
    assert zh2 is not None                      # retried across runs, not skipped
    assert len(calls) == n + 1


def test_content_flipflop_around_failure_never_serves_stale_original(tmp_path, monkeypatch):
    """A -> B(translation fails) -> A must NOT skip on the third run: the staged
    original still holds B, so serving the old A translation pair would publish
    a stale original. The both-files marker check forces a re-run."""
    calls: list = []
    n = bilingual.TRANSLATION_RETRIES

    def translate(content, src, tgt, engine=None, pbar=None):
        calls.append(1)
        # call 1: A ok; calls 2..1+n: B fails all retries; call 2+n: A again
        if 1 < len(calls) <= 1 + n:
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
    assert len(calls) == 1 + n + 1               # NOT skipped
    assert zh3 is not None
    assert "Hello world" in en3.read_text(encoding="utf-8")          # original is A


def test_retries_then_succeeds_within_one_write(tmp_path, monkeypatch):
    calls: list = []
    n = bilingual.TRANSLATION_RETRIES
    monkeypatch.setattr(
        bilingual, "translate_markdown_document",
        _fail_until(calls, succeed_after=n),
    )
    site = tmp_path / "website"
    site.mkdir()
    rel = Path("posts/retry.md")

    en, zh = bilingual.write_bilingual(site, rel, CONTENT, engine=Eng())
    assert zh is not None and en is not None
    assert len(calls) == n


def test_zh_to_en_failure_does_not_write_chinese_as_english(
    tmp_path, monkeypatch, capsys,
):
    calls: list = []
    n = bilingual.TRANSLATION_RETRIES
    monkeypatch.setattr(
        bilingual, "translate_markdown_document",
        _fail_until(calls, succeed_after=n + 1, result=EN_FROM_ZH),
    )
    site = tmp_path / "website"
    site.mkdir()
    rel = Path("posts/zh-src.md")

    en, zh = bilingual.write_bilingual(site, rel, ZH_CONTENT, engine=Eng())
    assert en is None
    assert zh is not None
    assert len(calls) == n
    en_file = site / "content" / rel
    assert not en_file.exists(), "must not publish Chinese at the English path"
    assert "这是一段中文" in zh.read_text(encoding="utf-8")

    captured = capsys.readouterr()
    assert "posts/zh-src.md" in captured.out
    assert "zh→en" in captured.out or "zh->en" in captured.out

    log = bilingual._failure_log_path().read_text(encoding="utf-8")
    assert "posts/zh-src.md" in log
    assert "zh->en" in log


def test_zh_to_en_failure_log_and_next_run_retries(
    tmp_path, monkeypatch, _isolate_failure_log,
):
    calls: list = []
    n = bilingual.TRANSLATION_RETRIES
    monkeypatch.setattr(
        bilingual, "translate_markdown_document",
        _fail_until(calls, succeed_after=n + 1, result=EN_FROM_ZH),
    )
    site = tmp_path / "website"
    site.mkdir()
    rel = Path("research/paper.md")

    bilingual.write_bilingual(site, rel, ZH_CONTENT, engine=Eng())
    en, zh = bilingual.write_bilingual(site, rel, ZH_CONTENT, engine=Eng())
    assert en is not None and zh is not None
    assert len(calls) == n + 1
    assert "English translation" in en.read_text(encoding="utf-8")
    assert "gadget:src-hash:v2:" in en.read_text(encoding="utf-8")
    # exhausted-then-success still logged the first write's failure
    log = (_isolate_failure_log / bilingual.TRANSLATION_FAILURE_LOG).read_text(
        encoding="utf-8")
    assert "research/paper.md" in log


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
