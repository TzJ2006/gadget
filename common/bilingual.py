"""Bilingual Hugo content generation using local translation inference."""

import logging
from pathlib import Path
from typing import Any, Optional

from common.engine import TranslationEngine, create_engine
from common.io import content_hash
from common.site_staging import resolve_site_staging_root, write_site_content
from common.translation import (
    detect_language,
    sanitize_frontmatter_language,
    translate_markdown_document,
    zh_path as translated_zh_path,
)

logger = logging.getLogger(__name__)


def _hash_marker(src_hash: str) -> str:
    """Invisible HTML comment stamped into BOTH staged files so a re-deploy of
    unchanged source skips the (5–15s) translation entirely. Both must match:
    checking only the translated side could serve a stale original after a
    content flip-flop around a failed translation."""
    return f"<!-- gadget:src-hash:{src_hash} -->"


def write_bilingual(
    hugo_site: Path,
    relative_path: Path,
    content: str,
    engine: TranslationEngine | None = None,
    model: str | None = None,
    pbar: Any | None = None,
    force: bool = False,
    overwrite_human: bool = False,
) -> tuple[Path, Optional[Path]]:
    """Write a Hugo content file in both languages.

    Detects the source language. Writes the original as the matching language
    version and translates to the other language.

    Before writing, frontmatter summary/description fields are sanity-checked:
    if they are in the wrong language for the source file, they are translated
    to the correct language first.

    - Chinese original -> write as ``.zh.md``, translate to English ``.md``
    - English original -> write as ``.md``, translate to Chinese ``.zh.md``

    Returns ``(en_path, zh_path)`` or ``(en_path, None)`` if translation fails.

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

    def _run(eng: TranslationEngine) -> tuple[Path, Optional[Path]]:
        fixed_content = sanitize_frontmatter_language(content, source_lang, eng)
        write_kwargs = {"force": force, "overwrite_human": overwrite_human}

        if source_lang == "zh":
            zh_rel = translated_zh_path(relative_path)
            zh_file_path = write_site_content(
                hugo_site, zh_rel, f"{fixed_content}\n\n{marker}\n", **write_kwargs)
            logger.info("Wrote Chinese version: %s", zh_file_path)

            try:
                en_content = translate_markdown_document(
                    fixed_content, "zh", "en", engine=eng, pbar=pbar,
                )
                en_path = write_site_content(
                    hugo_site, relative_path, f"{en_content}\n\n{marker}\n", **write_kwargs)
                logger.info("Wrote English translation: %s", en_path)
                return en_path, zh_file_path
            except ValueError as e:
                logger.warning("English translation produced invalid output, using Chinese as default: %s", e)
            except Exception as e:
                logger.warning("English translation failed, using Chinese as default: %s", e)
            en_path = write_site_content(hugo_site, relative_path, fixed_content, **write_kwargs)
            return en_path, zh_file_path
        else:
            en_path = write_site_content(
                hugo_site, relative_path, f"{fixed_content}\n\n{marker}\n", **write_kwargs)
            logger.info("Wrote English version: %s", en_path)

            try:
                zh_content = translate_markdown_document(
                    fixed_content, "en", "zh", engine=eng, pbar=pbar,
                )
                zh_rel = translated_zh_path(relative_path)
                zh_file_path = write_site_content(
                    hugo_site, zh_rel, f"{zh_content}\n\n{marker}\n", **write_kwargs)
                logger.info("Wrote Chinese translation: %s", zh_file_path)
                return en_path, zh_file_path
            except ValueError as e:
                logger.warning("Chinese translation produced invalid output, skipping: %s", e)
                return en_path, None
            except Exception as e:
                logger.warning("Chinese translation failed, skipping: %s", e)
                return en_path, None

    if engine is not None:
        return _run(engine)

    with create_engine(model) as eng:
        return _run(eng)
