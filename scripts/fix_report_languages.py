#!/usr/bin/env python3
"""Batch fix misnamed report files: rename Chinese .md → .zh.md, translate to English .md.

Handles three cases:
1. Chinese content in .md → rename to .zh.md + translate to English .md
2. .zh.md exists but .md is missing → translate .zh.md to English .md
3. .zh.md exists but .md has prompt leak (buggy) → re-translate

Usage:
    python scripts/fix_report_languages.py --dry-run    # Preview only
    python scripts/fix_report_languages.py              # Actually fix files
    python scripts/fix_report_languages.py --dir outputs/reports/summarize  # One dir only
"""

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.engine import TranslationEngine, create_engine
from common.io import atomic_write
from common.translation import translate_markdown_document

_engine: TranslationEngine | None = None


def _get_engine() -> TranslationEngine:
    global _engine
    if _engine is None:
        _engine = create_engine()
        _engine.load()
    return _engine


def _close_engine() -> None:
    global _engine
    if _engine is not None:
        _engine.unload()
        _engine = None


def detect_chinese(text: str, threshold: float = 0.05) -> bool:
    """Return True if the document has > threshold ratio of CJK characters.

    Measures the whole text (over non-whitespace chars), not just the first
    line \u2014 daily/weekly/monthly reports open with an English template header
    (``# Daily Report \u2014 \u2026``), so first-line sampling misclassifies
    Chinese-bodied reports as English and skips exactly the files to fix.
    """
    chars = [c for c in text if not c.isspace()]
    total = len(chars)
    if total == 0:
        return False
    cjk = sum(1 for c in chars if "\u4e00" <= c <= "\u9fff")
    return cjk / total > threshold


def is_buggy_translation(text: str) -> bool:
    """Return True if a translated file contains leaked prompt text."""
    head = text[:500]
    return "---BEGIN---" in head or "ONLY translate:" in head or "frontmatter delimiter" in head


def _zh_counterpart(md_path: Path) -> Path:
    """Return the .zh.md counterpart path for a .md file."""
    name = md_path.name
    if name.endswith("-monthly.md"):
        return md_path.parent / name.replace("-monthly.md", "-monthly.zh.md")
    if name.endswith("-weekly.md"):
        return md_path.parent / name.replace("-weekly.md", "-weekly.zh.md")
    return md_path.with_suffix(".zh.md")


def translate_zh_to_en(zh_path: Path, en_path: Path, *, dry_run: bool = False) -> bool:
    """Translate a .zh.md file to English .md."""
    if dry_run:
        print(f"  [dry-run] translate {zh_path.name} → {en_path.name}")
        return True

    zh_content = zh_path.read_text(encoding="utf-8")
    try:
        en_content = translate_markdown_document(zh_content, "zh", "en", engine=_get_engine())
        atomic_write(en_path, en_content)
        print(f"  [translated] {zh_path.name} → {en_path.name}")
        return True
    except Exception as e:
        print(f"  [error] Translation failed: {e}")
        return False


def scan_and_fix(directory: Path, *, dry_run: bool = False) -> tuple[int, int]:
    """Scan a directory and fix all language issues. Returns (fixed, failed)."""
    fixed, failed = 0, 0

    for f in sorted(directory.glob("*.md")):
        if f.name.endswith(".zh.md"):
            continue
        try:
            content = f.read_text(encoding="utf-8")
        except OSError:
            continue
        if not detect_chinese(content):
            continue

        zh_path = _zh_counterpart(f)
        if dry_run:
            print(f"  [dry-run] rename {f.name} → {zh_path.name}")
        elif zh_path.exists():
            # Don't clobber an existing .zh.md (silent loss on POSIX,
            # FileExistsError crash on Windows).
            print(f"  [skip] {zh_path.name} 已存在，跳过重命名 {f.name}")
        else:
            f.rename(zh_path)
            print(f"  [renamed] {f.name} → {zh_path.name}")

    for zh_file in sorted(directory.glob("*.zh.md")):
        name = zh_file.name
        if name.endswith("-monthly.zh.md"):
            en_name = name.replace("-monthly.zh.md", "-monthly.md")
        elif name.endswith("-weekly.zh.md"):
            en_name = name.replace("-weekly.zh.md", "-weekly.md")
        else:
            en_name = name.replace(".zh.md", ".md")
        en_path = zh_file.parent / en_name

        needs_translate = False
        if not en_path.exists():
            needs_translate = True
            reason = "missing"
        else:
            en_content = en_path.read_text(encoding="utf-8")
            if is_buggy_translation(en_content):
                needs_translate = True
                reason = "buggy"
            elif detect_chinese(en_content):
                needs_translate = True
                reason = "still Chinese"

        if needs_translate:
            print(f"  [{reason}] {en_name}")
            ok = translate_zh_to_en(zh_file, en_path, dry_run=dry_run)
            if ok:
                fixed += 1
            else:
                failed += 1

    return fixed, failed


def main():
    parser = argparse.ArgumentParser(description="Fix misnamed Chinese/English report files")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, don't change files")
    parser.add_argument("--dir", type=Path, help="Only fix files in this directory")
    args = parser.parse_args()

    default_dirs = [
        ROOT / "outputs" / "reports" / "summarize",
    ]
    dirs = [args.dir] if args.dir else default_dirs

    total_fixed, total_failed = 0, 0
    for d in dirs:
        if not d.is_dir():
            print(f"[skip] {d} does not exist")
            continue

        print(f"\n=== {d} ===\n")
        f, fail = scan_and_fix(d, dry_run=args.dry_run)
        total_fixed += f
        total_failed += fail

    _close_engine()

    label = "[dry-run] " if args.dry_run else ""
    print(f"\n{label}Done: {total_fixed} translated, {total_failed} failed")


if __name__ == "__main__":
    main()
