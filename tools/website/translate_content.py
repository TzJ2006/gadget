"""Ad-hoc CLI for bilingual Hugo pairs. Delegates to translate_site_batch.

Usage:
    python translate_content.py <file_or_dir> --to <lang>
    python translate_content.py content/posts/my-post.md --to zh
    python translate_content.py content/posts/ --to zh --recursive

This is not a separate translator: it calls translate_site_batch.run() so
pair planning, state tracking, and generated-page skipping stay in one place.
Pipeline-generated pages are skipped unless --include-generated is passed.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

SITE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = SITE_ROOT.parent.parent
if str(SITE_ROOT) not in sys.path:
    sys.path.insert(0, str(SITE_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from common.engine import DEFAULT_TRANSLATION_MODEL
import translate_site_batch as batch


def _run_adhoc(
    target: Path,
    *,
    target_lang: str,
    model: str,
    dry_run: bool,
    recursive: bool,
    include_index: bool,
    include_generated: bool,
    full: bool = False,
    state_file: str | None = None,
    verbose: bool = False,
) -> int:
    """Map an ad-hoc file/dir request onto translate_site_batch.run()."""
    target = Path(target).resolve()

    def predicate(pair: batch.PairInfo) -> bool:
        if target.is_file():
            return True
        if not include_index and pair.en_path.name == "_index.md":
            return False
        return True

    return batch.run(
        roots=[target],
        excluded=[],
        state_path=Path(state_file).resolve() if state_file else batch.STATE_FILE,
        model=model,
        force_full=full,
        dry_run=dry_run,
        verbose=verbose,
        include_generated=include_generated,
        recursive=recursive if target.is_dir() else True,
        pair_predicate=predicate,
        only_target_lang=target_lang,
    )


def translate_file(
    path: Path,
    target_lang: str,
    engine=None,
    model: str | None = None,
    dry_run: bool = False,
    include_generated: bool = False,
) -> int:
    """Sync the en/zh pair for one markdown file via translate_site_batch.

    ``engine`` is ignored; the batch runner loads its own translation engine.
    """
    del engine
    return _run_adhoc(
        Path(path),
        target_lang=target_lang,
        model=model or DEFAULT_TRANSLATION_MODEL,
        dry_run=dry_run,
        recursive=True,
        include_index=True,
        include_generated=include_generated,
    )


def translate_directory(
    directory: Path,
    target_lang: str,
    model: str | None = None,
    recursive: bool = False,
    dry_run: bool = False,
    include_index: bool = False,
    include_generated: bool = False,
) -> int:
    """Sync en/zh pairs under a directory via translate_site_batch."""
    return _run_adhoc(
        Path(directory),
        target_lang=target_lang,
        model=model or DEFAULT_TRANSLATION_MODEL,
        dry_run=dry_run,
        recursive=recursive,
        include_index=include_index,
        include_generated=include_generated,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Translate Hugo content between English and Chinese "
        "(wrapper around translate_site_batch)",
    )
    parser.add_argument("path", help="File or directory to translate")
    parser.add_argument(
        "--to",
        required=True,
        choices=["en", "zh"],
        help="Only produce this target language",
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
        help="Include _index.md files (skipped by default in directory mode)",
    )
    parser.add_argument(
        "--include-generated",
        action="store_true",
        help="Translate pipeline-generated pages (skipped by default)",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Force retranslating pairs even when both language files exist",
    )
    parser.add_argument(
        "--state-file",
        default=str(batch.STATE_FILE),
        help=f"Translation state file (default: {batch.STATE_FILE.name})",
    )
    args = parser.parse_args()

    target = Path(args.path)
    if not target.exists():
        print(f"Path not found: {target}", file=sys.stderr)
        sys.exit(1)

    sys.exit(
        _run_adhoc(
            target,
            target_lang=args.to,
            model=args.model,
            dry_run=args.dry_run,
            recursive=args.recursive,
            include_index=args.include_index,
            include_generated=args.include_generated,
            full=args.full,
            state_file=args.state_file,
        )
    )


if __name__ == "__main__":
    main()
