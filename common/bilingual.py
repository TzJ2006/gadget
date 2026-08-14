"""Bilingual Hugo content generation using local translation inference."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from common.engine import TranslationEngine, create_engine
from common.io import content_hash
from common.paths import LOGS_DIR
from common.site_staging import resolve_site_staging_root, write_site_content
from common.translation import (
    detect_language,
    sanitize_frontmatter_language,
    translate_markdown_document,
    zh_path as translated_zh_path,
)

logger = logging.getLogger(__name__)


# Bump when the pipeline changes what it emits for the same source, so already
# staged pages re-translate once instead of being skipped forever by their
# still-matching src-hash. v2: frontmatter title/keywords/tags are translated too.
_MARKER_VERSION = "2"

# Attempts per article (first try + retries) before giving up on a direction.
TRANSLATION_RETRIES = 3
TRANSLATION_FAILURE_LOG = "translation-failures.log"


def _hash_marker(src_hash: str) -> str:
    """Invisible HTML comment stamped into BOTH staged files so a re-deploy of
    unchanged source skips the (5–15s) translation entirely. Both must match:
    checking only the translated side could serve a stale original after a
    content flip-flop around a failed translation."""
    return f"<!-- gadget:src-hash:v{_MARKER_VERSION}:{src_hash} -->"


def _failure_log_path() -> Path:
    return LOGS_DIR / TRANSLATION_FAILURE_LOG


def _record_translation_failure(
    relative_path: Path, src: str, tgt: str, exc: BaseException,
) -> None:
    """Append the failed article to outputs/logs and print it to the terminal."""
    attempts = max(1, TRANSLATION_RETRIES)
    article = Path(relative_path).as_posix()
    line = (
        f"[warn] translation {src}→{tgt} failed for {article} "
        f"after {attempts} attempts"
    )
    print(line, flush=True)
    logger.warning("%s: %s", line, exc)
    log_path = _failure_log_path()
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().isoformat(timespec="seconds")
        with log_path.open("a", encoding="utf-8") as f:
            f.write(f"{stamp}\t{article}\t{src}->{tgt}\t{exc}\n")
    except OSError as e:
        logger.warning("Could not write translation failure log %s: %s", log_path, e)


def _translate_with_retries(
    content: str,
    src: str,
    tgt: str,
    engine: TranslationEngine,
    pbar: Any | None,
) -> str:
    """Call ``translate_markdown_document``, retrying up to TRANSLATION_RETRIES."""
    attempts = max(1, TRANSLATION_RETRIES)
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return translate_markdown_document(
                content, src, tgt, engine=engine, pbar=pbar,
            )
        except Exception as e:
            last = e
            kind = "invalid output" if isinstance(e, ValueError) else "failed"
            logger.warning(
                "%s→%s translation %s (attempt %d/%d): %s",
                src, tgt, kind, attempt, attempts, e,
            )
    assert last is not None
    raise last


def write_bilingual(
    hugo_site: Path,
    relative_path: Path,
    content: str,
    engine: TranslationEngine | None = None,
    model: str | None = None,
    pbar: Any | None = None,
    force: bool = False,
    overwrite_human: bool = False,
) -> tuple[Optional[Path], Optional[Path]]:
    """Write a Hugo content file in both languages.

    Detects the source language. Writes the original as the matching language
    version and translates to the other language.

    Before writing, frontmatter summary/description fields are sanity-checked:
    if they are in the wrong language for the source file, they are translated
    to the correct language first.

    - Chinese original -> write as ``.zh.md``, translate to English ``.md``
    - English original -> write as ``.md``, translate to Chinese ``.zh.md``

    Returns ``(en_path, zh_path)``. The source-language file is always written.
    A failed translation (after ``TRANSLATION_RETRIES`` attempts) leaves the
    other side ``None`` and does **not** copy source text into that language's
    page — so a zh→en failure never publishes Chinese at the English ``.md``.

    Re-runs with byte-identical source are free: the translated file carries a
    ``gadget:src-hash`` marker, and when it matches the current source hash both
    staged files are left untouched (no engine call, no rewrite) — even under
    ``force`` (identical output would be rewritten for nothing).

    ``force=True`` backs up previously written files before overwriting them
    (outputs/backups/website-force/). Existing files without a gadget marker
    are human-written and raise ``HumanContentError`` unless
    ``overwrite_human=True``.
    """
    source_lang = detect_language(content)
    relative_path = Path(relative_path)

    src_hash = content_hash(content)
    marker = _hash_marker(src_hash)
    original_rel = translated_zh_path(relative_path) if source_lang == "zh" else relative_path
    translated_rel = relative_path if source_lang == "zh" else translated_zh_path(relative_path)
    staging_content = resolve_site_staging_root(hugo_site) / "content"
    orig_file = staging_content / original_rel
    trans_file = staging_content / translated_rel
    try:
        if (orig_file.exists() and trans_file.exists()
                and marker in trans_file.read_text(encoding="utf-8")
                and marker in orig_file.read_text(encoding="utf-8")):
            logger.info("Translation current for %s (src-hash %s) — skipping",
                        relative_path, src_hash)
            return (trans_file, orig_file) if source_lang == "zh" else (orig_file, trans_file)
    except OSError:
        pass  # unreadable staged file → fall through and re-translate

    def _run(eng: TranslationEngine) -> tuple[Optional[Path], Optional[Path]]:
        fixed_content = sanitize_frontmatter_language(content, source_lang, eng)
        write_kwargs = {"force": force, "overwrite_human": overwrite_human}

        if source_lang == "zh":
            zh_rel = translated_zh_path(relative_path)
            zh_file_path = write_site_content(
                hugo_site, zh_rel, f"{fixed_content}\n\n{marker}\n", **write_kwargs)
            logger.info("Wrote Chinese version: %s", zh_file_path)

            try:
                en_content = _translate_with_retries(
                    fixed_content, "zh", "en", eng, pbar,
                )
            except Exception as e:
                _record_translation_failure(relative_path, "zh", "en", e)
                return None, zh_file_path
            en_path = write_site_content(
                hugo_site, relative_path, f"{en_content}\n\n{marker}\n", **write_kwargs)
            logger.info("Wrote English translation: %s", en_path)
            return en_path, zh_file_path
        else:
            en_path = write_site_content(
                hugo_site, relative_path, f"{fixed_content}\n\n{marker}\n", **write_kwargs)
            logger.info("Wrote English version: %s", en_path)

            try:
                zh_content = _translate_with_retries(
                    fixed_content, "en", "zh", eng, pbar,
                )
            except Exception as e:
                _record_translation_failure(relative_path, "en", "zh", e)
                return en_path, None
            zh_rel = translated_zh_path(relative_path)
            zh_file_path = write_site_content(
                hugo_site, zh_rel, f"{zh_content}\n\n{marker}\n", **write_kwargs)
            logger.info("Wrote Chinese translation: %s", zh_file_path)
            return en_path, zh_file_path

    if engine is not None:
        return _run(engine)

    with create_engine(model) as eng:
        return _run(eng)
