"""Tiny fixtures shared by website script tests. Not collected by pytest."""

from __future__ import annotations

from pathlib import Path

WEBSITE_ROOT = Path(__file__).resolve().parent.parent

# Long enough for preflight MIN_BODY_LENGTH (100) and language detection.
EN_BODY = (
    "This is a long enough English body for language detection to stay stable. "
    "It mentions Hugo, bilingual markdown, and the website publish pipeline. "
    "Extra filler keeps us well above the one-hundred-character minimum.\n"
)

ZH_BODY = (
    "这是一段足够长的中文正文，用来判断语言检测是否可靠工作。"
    "内容覆盖网站发布、双语配对和预检流程。"
    "再补一些文字确保长度超过检测阈值。"
    "继续补充中文内容，避免预检把短正文当成无法判定语言而跳过。"
    "最后再写一句，保证总字数稳定超过一百个字符。\n"
)


def write_md(path: Path, title: str, body: str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\ntitle: {title}\n---\n\n{body}", encoding="utf-8")
    return path


def generated_skip_paths(content_root: Path) -> list[Path]:
    """Same generated dirs/files preflight skips — used as ``--exclude`` paths."""
    try:
        import generated_paths as gp  # optional sibling module
        dirs, files = gp.GENERATED_CONTENT_DIRS, gp.GENERATED_CONTENT_FILES
    except ImportError:
        import preflight_check as pf
        dirs, files = pf.GENERATED_CONTENT_DIRS, pf.GENERATED_CONTENT_FILES
    return [content_root / p for p in (*dirs, *files)]
