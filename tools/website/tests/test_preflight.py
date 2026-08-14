"""Preflight pairing, generated-dir skip, and exit codes.

Mocks the translation engine (``--no-fix`` / no ``create_engine``). No network.

Run: ``python -m pytest tools/website/tests/test_preflight.py -q``
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

pytest.importorskip("yaml")

import preflight_check as pf

from helpers import EN_BODY, ZH_BODY, write_md


# ── generated-dir skip ─────────────────────────────────────────────


@pytest.mark.parametrize(
    "rel, expected",
    [
        ("bugJournal/daily/2026-01-01.md", True),
        ("bugJournal/weekly/2026-W01.md", True),
        ("bugJournal/monthly/2026-01.md", True),
        ("research/paper.md", True),
        ("benchmark.md", True),
        ("benchmark.zh.md", True),
        ("bugJournal/_index.md", False),
        ("posts/hello.md", False),
        ("Search.md", False),
    ],
)
def test_is_generated_matches_pipeline_skip_list(tmp_path, rel, expected):
    root = tmp_path / "content"
    assert pf._is_generated(root / rel, root) is expected


def test_find_modified_files_skips_generated_dirs_and_benchmark(tmp_path):
    content = tmp_path / "content"
    write_md(content / "posts" / "hand.md", "Hand", EN_BODY)
    write_md(content / "bugJournal" / "_index.md", "Journal", EN_BODY)
    write_md(content / "research" / "paper.md", "Paper", EN_BODY)
    write_md(content / "bugJournal" / "daily" / "2026-01-01.md", "Day", EN_BODY)
    write_md(content / "bugJournal" / "weekly" / "2026-W01.md", "Week", EN_BODY)
    write_md(content / "bugJournal" / "monthly" / "2026-01.md", "Month", EN_BODY)
    write_md(content / "benchmark.md", "Bench", EN_BODY)

    found = {
        p.relative_to(content).as_posix()
        for p in pf.find_modified_files(content, since=0.0)
    }
    assert "posts/hand.md" in found
    assert "bugJournal/_index.md" in found
    assert "research/paper.md" not in found
    assert "bugJournal/daily/2026-01-01.md" not in found
    assert "bugJournal/weekly/2026-W01.md" not in found
    assert "bugJournal/monthly/2026-01.md" not in found
    assert "benchmark.md" not in found


# ── bilingual pairing ──────────────────────────────────────────────


def test_counterpart_path_round_trips():
    en = Path("posts/note.md")
    zh = Path("posts/note.zh.md")
    assert pf.counterpart_path(en) == zh
    assert pf.counterpart_path(zh) == en
    assert pf.is_zh_file(zh) and not pf.is_zh_file(en)


def test_check_bilingual_pairs_reports_missing_counterpart(tmp_path):
    path = write_md(tmp_path / "note.md", "Note", EN_BODY)
    issues = pf.check_bilingual_pairs([path])
    assert len(issues) == 1
    issue = issues[0]
    assert issue.level == "FIX" and issue.check == "pair"
    assert issue.extra["missing_path"].endswith("note.zh.md")
    assert issue.extra["slot"] == "en"
    assert issue.extra["needs_swap"] is False


def test_check_bilingual_pairs_silent_when_both_exist(tmp_path):
    en = write_md(tmp_path / "note.md", "Note", EN_BODY)
    zh = write_md(tmp_path / "note.zh.md", "笔记标题够长了", ZH_BODY)
    assert pf.check_bilingual_pairs([en, zh]) == []


def test_check_bilingual_pairs_flags_swap_when_slot_language_mismatches(tmp_path):
    """English filename holding Chinese body → copy to .zh.md then translate."""
    path = write_md(tmp_path / "note.md", "Note", ZH_BODY)
    issues = pf.check_bilingual_pairs([path])
    assert len(issues) == 1
    assert issues[0].extra["needs_swap"] is True
    assert issues[0].extra["existing_lang"] == "zh"


# ── CLI exit codes (engine never loaded) ───────────────────────────


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "SITE_ROOT", tmp_path)
    (tmp_path / "content").mkdir()
    (tmp_path / "static" / "images").mkdir(parents=True)
    return tmp_path


def _run_main(monkeypatch, *extra: str) -> int:
    monkeypatch.setattr(sys, "argv", ["preflight_check.py", "--no-fix", *extra])
    return pf.main()


def test_main_exit_0_when_nothing_is_newer_than_timestamp(site, monkeypatch):
    write_md(site / "content" / "a.md", "A", EN_BODY)
    ts = site / ".last_build"
    ts.write_text("", encoding="utf-8")
    future = time.time() + 10_000
    os.utime(ts, (future, future))
    assert _run_main(monkeypatch) == 0


def test_main_exit_0_when_only_generated_content_changed(site, monkeypatch):
    """Generated trees are skipped, so an unpaired research page is not a FIX."""
    write_md(site / "content" / "research" / "paper.md", "Paper", EN_BODY)
    write_md(site / "content" / "benchmark.md", "Bench", EN_BODY)
    assert _run_main(monkeypatch) == 0


def test_main_exit_0_when_handwritten_pair_is_valid(site, monkeypatch):
    write_md(site / "content" / "a.md", "A", EN_BODY)
    write_md(site / "content" / "a.zh.md", "甲侧标题够长了", ZH_BODY)
    assert _run_main(monkeypatch) == 0


def test_main_exit_1_on_missing_frontmatter(site, monkeypatch):
    (site / "content" / "bad.md").write_text(
        "no frontmatter here but a long enough body to be noticed " * 4,
        encoding="utf-8",
    )
    assert _run_main(monkeypatch) == 1


def test_main_exit_1_on_missing_title(site, monkeypatch):
    (site / "content" / "bad.md").write_text(
        "---\ndate: 2026-01-01\n---\n\n" + EN_BODY,
        encoding="utf-8",
    )
    assert _run_main(monkeypatch) == 1


def test_main_exit_2_on_uncompressed_jpeg(site, monkeypatch):
    write_md(site / "content" / "a.md", "A", EN_BODY)
    write_md(site / "content" / "a.zh.md", "甲侧标题够长了", ZH_BODY)
    (site / "static" / "images" / "photo.jpg").write_bytes(b"fake-jpeg")
    assert _run_main(monkeypatch) == 2


def test_main_exit_2_on_stale_static_link(site, monkeypatch):
    body = EN_BODY + "\n![x](../../static/images/foo.png)\n"
    write_md(site / "content" / "a.md", "A", body)
    write_md(site / "content" / "a.zh.md", "甲侧标题够长了", ZH_BODY)
    assert _run_main(monkeypatch) == 2


def test_main_block_wins_over_warnings(site, monkeypatch):
    (site / "content" / "bad.md").write_text("not yaml " * 20, encoding="utf-8")
    (site / "static" / "images" / "photo.jpg").write_bytes(b"fake-jpeg")
    assert _run_main(monkeypatch) == 1


def test_no_fix_never_loads_translation_engine(site, monkeypatch):
    write_md(site / "content" / "solo.md", "Solo", EN_BODY)

    def boom():
        raise AssertionError("engine must not load under --no-fix")

    monkeypatch.setattr(pf, "_load_translation_engine", boom)
    # Missing pair is FIX, not WARN — with --no-fix the exit is 0.
    assert _run_main(monkeypatch) == 0
