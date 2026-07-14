"""Translate Hugo content files between English and Chinese.

Usage:
    python translate_content.py <file_or_dir> --to <lang>
    python translate_content.py content/posts/my-post.md --to zh
    python translate_content.py content/bugJournal/daily/ --to en

Supports:
    - Single file translation
    - Batch directory translation (non-recursive by default, --recursive for deep)
    - Frontmatter-aware: translates title, summary, description; preserves other fields
    - Language detection: skips files already in the target language
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from common.engine import TranslationEngine, create_engine, DEFAULT_TRANSLATION_MODEL
from common.io import atomic_write
from common.translation import LANG_NAMES, detect_language, translate_markdown_document

logger = logging.getLogger(__name__)


def _parse_frontmatter(text: str) -> tuple[str, str]:
    """Split a markdown file into frontmatter and body."""
    match = re.match(r"^(---\s*\n.*?\n---\s*\n)(.*)", text, re.DOTALL)
    if match:
        return match.group(1), match.group(2)
    return "", text


def _output_path(source: Path, target_lang: str) -> Path:
    """Compute the output path for a translated file."""
    stem = source.stem
    for lang in ("en", "zh"):
        if stem.endswith(f".{lang}"):
            stem = stem[: -(len(lang) + 1)]
            break
    if target_lang == "en":
        return source.parent / f"{stem}.md"
    return source.parent / f"{stem}.{target_lang}.md"


def translate_file(
    path: Path,
    target_lang: str,
    engine: TranslationEngine | None = None,
    model: str | None = None,
    dry_run: bool = False,
) -> Path | None:
    """Translate a single markdown file. Returns output path or None on skip/error."""
    path = Path(path)
    if not path.exists():
        logger.error("File not found: %s", path)
        return None

    content = path.read_text(encoding="utf-8")
    if not content.strip():
        logger.warning("Empty file, skipping: %s", path)
        return None

    _, body = _parse_frontmatter(content)
    source_lang = detect_language(body or content)

    if source_lang == target_lang:
        logger.info("Already in %s, skipping: %s", LANG_NAMES[target_lang], path)
        return None

    out = _output_path(path, target_lang)

    relocate = False
    zh_path = _output_path(path, "zh")
    if source_lang == "zh" and target_lang == "en" and out == path:
        if zh_path.exists():
            logger.info("Chinese version already exists at %s, skipping: %s", zh_path, path)
            return None
        relocate = True
        if dry_run:
            logger.info("[DRY RUN] Would relocate %s → %s and translate to English", path, zh_path)
            return out
        atomic_write(zh_path, content)
        logger.info("Relocated Chinese content: %s → %s", path.name, zh_path.name)
    elif out.exists():
        logger.info("Translation already exists, skipping: %s", out)
        return None

    if dry_run:
        logger.info("[DRY RUN] Would translate %s → %s", path, out)
        return out

    logger.info(
        "Translating %s → %s: %s",
        LANG_NAMES[source_lang],
        LANG_NAMES[target_lang],
        path.name,
    )

    try:
        result = translate_markdown_document(
            content,
            source_lang,
            target_lang,
            engine=engine,
            model=model,
        )
    except RuntimeError as exc:
        logger.error("Translation failed for %s: %s", path, exc)
        if relocate and zh_path.exists():
            zh_path.unlink()
            logger.info("Rolled back relocation: removed %s", zh_path)
        return None

    atomic_write(out, result)
    logger.info("Wrote: %s", out)
    return out


def translate_directory(
    directory: Path,
    target_lang: str,
    model: str | None = None,
    recursive: bool = False,
    dry_run: bool = False,
    include_index: bool = False,
) -> list[Path]:
    """Translate all .md files in a directory. Returns list of output paths."""
    directory = Path(directory)
    pattern = "**/*.md" if recursive else "*.md"
    results = []

    md_files = sorted(directory.glob(pattern))
    source_files = [
        f
        for f in md_files
        if not any(f.stem.endswith(f".{lang}") for lang in ("en", "zh"))
        and (include_index or f.name != "_index.md")
    ]

    logger.info(
        "Found %d source files in %s (recursive=%s)",
        len(source_files),
        directory,
        recursive,
    )

    if dry_run:
        for source in source_files:
            out = translate_file(source, target_lang, model=model, dry_run=True)
            if out is not None:
                results.append(out)
        return results

    with create_engine(model) as engine:
        for source in source_files:
            out = translate_file(
                source, target_lang, engine=engine, model=model, dry_run=False,
            )
            if out is not None:
                results.append(out)
    return results


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Translate Hugo content between English and Chinese"
    )
    parser.add_argument("path", help="File or directory to translate")
    parser.add_argument(
        "--to",
        required=True,
        choices=["en", "zh"],
        help="Target language",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_TRANSLATION_MODEL,
        help=f"Translation model (default: {DEFAULT_TRANSLATION_MODEL})",
    )
    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Process directories recursively",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be translated without doing it",
    )
    parser.add_argument(
        "--include-index",
        action="store_true",
        help="Include _index.md files (skipped by default)",
    )
    args = parser.parse_args()

    target = Path(args.path)
    if target.is_file():
        result = translate_file(
            target,
            args.to,
            model=args.model,
            dry_run=args.dry_run,
        )
        if result:
            print(f"Done: {result}")
        else:
            print("No translation needed or error occurred.")
    elif target.is_dir():
        results = translate_directory(
            target,
            args.to,
            model=args.model,
            recursive=args.recursive,
            dry_run=args.dry_run,
            include_index=args.include_index,
        )
        print(f"Translated {len(results)} files.")
    else:
        print(f"Path not found: {target}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
