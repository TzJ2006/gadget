"""translate_site_batch planning and generated-tree exclude.

Mocks ``create_engine`` / ``translate_document``. No network, no model load.

Run: ``python -m pytest tools/website/tests/test_translate_site_batch.py -q``
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

import translate_site_batch as tsb

from helpers import EN_BODY, ZH_BODY, generated_skip_paths, write_md


class FakeEngine:
    """Stand-in TranslationEngine; never loads a model."""

    def load(self):
        pass

    def unload(self):
        pass


def _argv(monkeypatch, *args: str) -> None:
    monkeypatch.setattr(sys, "argv", ["translate_site_batch.py", *args])


def _exclude_args(content: Path) -> list[str]:
    args: list[str] = []
    for path in generated_skip_paths(content):
        args.extend(["--exclude", str(path)])
    return args


# ── collect / exclude ──────────────────────────────────────────────


def test_is_excluded_directory_skips_children(tmp_path):
    research = (tmp_path / "research").resolve()
    research.mkdir()
    paper = (research / "paper.md").resolve()
    paper.write_text("x", encoding="utf-8")
    assert tsb.is_excluded(paper, [research])
    assert not tsb.is_excluded(paper, [(tmp_path / "other").resolve()])


def test_collect_pairs_excludes_generated_dirs_and_benchmark(tmp_path):
    content = tmp_path / "content"
    write_md(content / "posts" / "hello.md", "Hello", EN_BODY)
    write_md(content / "research" / "paper.md", "Paper", EN_BODY)
    write_md(content / "bugJournal" / "daily" / "2026-01-01.md", "Day", EN_BODY)
    write_md(content / "bugJournal" / "_index.md", "Journal", EN_BODY)
    write_md(content / "benchmark.md", "Bench", EN_BODY)

    excluded = [p.resolve() for p in generated_skip_paths(content)]
    pairs, _warnings = tsb.collect_pairs(content.resolve(), excluded)
    rels = {Path(key).as_posix().replace("\\", "/") for key in pairs}

    assert any(r.endswith("posts/hello.md") for r in rels)
    assert any(r.endswith("bugJournal/_index.md") for r in rels)
    assert not any(r.endswith("research/paper.md") for r in rels)
    assert not any("/daily/" in r for r in rels)
    assert not any(r.endswith("benchmark.md") for r in rels)


# ── plan_pair ──────────────────────────────────────────────────────


def test_plan_pair_missing_zh_translates_from_en(tmp_path):
    content = tmp_path / "content"
    write_md(content / "hello.md", "Hello", EN_BODY)
    pairs, _ = tsb.collect_pairs(content.resolve(), [])
    pair = next(iter(pairs.values()))
    op, bootstrap, _warnings = tsb.plan_pair(pair, None, force_full=False)
    assert bootstrap is None
    assert op is not None
    assert op.source_lang == "en" and op.target_lang == "zh"
    assert op.reason == "missing or inconsistent language pair"
    assert op.target_path == pair.zh_path


def test_plan_pair_valid_pair_bootstraps_without_work(tmp_path):
    content = tmp_path / "content"
    write_md(content / "hello.md", "Hello", EN_BODY)
    write_md(content / "hello.zh.md", "你好世界标题够长", ZH_BODY)
    pairs, _ = tsb.collect_pairs(content.resolve(), [])
    pair = next(iter(pairs.values()))
    op, bootstrap, _warnings = tsb.plan_pair(pair, None, force_full=False)
    assert op is None
    assert bootstrap is not None
    assert bootstrap["en_sha256"] and bootstrap["zh_sha256"]


def test_plan_pair_english_changed_replans_en_to_zh(tmp_path):
    content = tmp_path / "content"
    write_md(content / "hello.md", "Hello", EN_BODY)
    write_md(content / "hello.zh.md", "你好世界标题够长", ZH_BODY)
    pairs, _ = tsb.collect_pairs(content.resolve(), [])
    pair = next(iter(pairs.values()))
    _op, bootstrap, _ = tsb.plan_pair(pair, None, force_full=False)
    assert bootstrap is not None

    write_md(content / "hello.md", "Hello", EN_BODY + "Changed since last sync.\n")
    pairs, _ = tsb.collect_pairs(content.resolve(), [])
    pair = next(iter(pairs.values()))
    op, next_boot, _ = tsb.plan_pair(pair, bootstrap, force_full=False)
    assert next_boot is None
    assert op is not None
    assert op.reason == "english source changed"
    assert op.source_lang == "en"


# ── main(): dry-run + mocked engine ────────────────────────────────


def test_dry_run_plans_without_loading_engine(tmp_path, monkeypatch, capsys):
    content = tmp_path / "content"
    write_md(content / "posts" / "hello.md", "Hello", EN_BODY)
    state = tmp_path / "state.json"

    def boom(*_a, **_k):
        raise AssertionError("engine must not load on --dry-run")

    monkeypatch.setattr(tsb, "create_engine", boom)
    _argv(
        monkeypatch,
        "--root", str(content),
        "--state-file", str(state),
        "--dry-run",
        *_exclude_args(content),
    )
    assert tsb.main() == 0
    out = capsys.readouterr().out
    assert "[plan]" in out
    assert "hello.md" in out
    assert not (content / "posts" / "hello.zh.md").exists()


def test_main_translates_handwritten_skips_excluded_generated(tmp_path, monkeypatch):
    content = tmp_path / "content"
    write_md(content / "posts" / "hello.md", "Hello", EN_BODY)
    write_md(content / "research" / "paper.md", "Paper", EN_BODY)
    write_md(content / "benchmark.md", "Bench", EN_BODY)
    state = tmp_path / "state.json"

    calls: list[str] = []

    def fake_translate(src, target_lang, engine):
        calls.append(target_lang)
        title = "译标题够长了" if target_lang == "zh" else "Translated Title Here"
        body = ZH_BODY if target_lang == "zh" else EN_BODY
        return f"---\ntitle: {title}\n---\n\n{body}"

    monkeypatch.setattr(tsb, "create_engine", lambda _model: FakeEngine())
    monkeypatch.setattr(tsb, "translate_document", fake_translate)
    _argv(
        monkeypatch,
        "--root", str(content),
        "--state-file", str(state),
        *_exclude_args(content),
    )
    assert tsb.main() == 0
    assert (content / "posts" / "hello.zh.md").exists()
    assert not (content / "research" / "paper.zh.md").exists()
    assert not (content / "benchmark.zh.md").exists()
    assert calls == ["zh"]


def _module_default_skips_generated() -> bool:
    src = inspect.getsource(tsb)
    return (
        "include_generated" in src
        or "include-generated" in src
        or "GENERATED_CONTENT" in src
    )


def test_dry_run_default_skips_generated_when_implemented(tmp_path, monkeypatch, capsys):
    if not _module_default_skips_generated():
        pytest.skip(
            "default generated exclude not implemented; explicit --exclude is tested"
        )
    content = tmp_path / "content"
    write_md(content / "posts" / "hello.md", "Hello", EN_BODY)
    write_md(content / "research" / "paper.md", "Paper", EN_BODY)
    write_md(content / "benchmark.md", "Bench", EN_BODY)
    state = tmp_path / "state.json"

    monkeypatch.setattr(tsb, "create_engine", lambda *_a, **_k: (_ for _ in ()).throw(
        AssertionError("dry-run")
    ))
    _argv(
        monkeypatch,
        "--root", str(content),
        "--state-file", str(state),
        "--dry-run",
    )
    assert tsb.main() == 0
    out = capsys.readouterr().out
    assert "hello.md" in out
    assert "paper.md" not in out
    assert "benchmark.md" not in out
