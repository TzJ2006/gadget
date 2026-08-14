"""Unit tests for scripts/language.py — counterpart paths, no engine/LLM.

Run: python -m pytest scripts/tests/test_language.py -q
"""

from pathlib import Path

import language


def test_counterparts_roundtrip_daily():
    en = Path("outputs/reports/summarize/2026-03-14.md")
    zh = language._zh_counterpart(en)
    assert zh.name == "2026-03-14.zh.md"
    assert language._en_counterpart(zh) == en


def test_counterparts_roundtrip_weekly_monthly():
    weekly = Path("outputs/reports/summarize/2026-W12-weekly.md")
    assert language._zh_counterpart(weekly).name == "2026-W12-weekly.zh.md"
    assert language._en_counterpart(language._zh_counterpart(weekly)) == weekly

    monthly = Path("outputs/reports/summarize/2026-02-monthly.md")
    assert language._zh_counterpart(monthly).name == "2026-02-monthly.zh.md"
    assert language._en_counterpart(language._zh_counterpart(monthly)) == monthly


def test_cli_subcommands(capsys):
    import sys
    from unittest.mock import patch

    with patch.object(sys, "argv", ["language.py", "--help"]):
        try:
            language.main()
        except SystemExit as e:
            assert e.code == 0
    out = capsys.readouterr().out
    assert "hugo" in out
    assert "reports" in out


def test_scan_and_fix_renames_chinese_md(tmp_path, monkeypatch):
    md = tmp_path / "2026-W12-weekly.md"
    md.write_text("# Weekly Report\n\n这是中文正文，需要重命名为 zh 文件。\n", encoding="utf-8")
    monkeypatch.setattr(language, "translate_zh_to_en", lambda *a, **k: True)
    language.scan_and_fix(tmp_path, dry_run=False)
    assert not md.exists()
    zh = tmp_path / "2026-W12-weekly.zh.md"
    assert zh.exists()
    assert language._en_counterpart(zh).name == "2026-W12-weekly.md"
