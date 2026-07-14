"""Helpers that write auto-generated Hugo content/static files into a Hugo site.

Since the 2026-07 single-content-root migration, generated content goes
directly into ``<hugo_site>/content`` and ``<hugo_site>/static`` (default site:
``tools/website``) — there is no separate ``outputs/site`` staging tree and no
Hugo ``module.mounts``. Generated and human-written posts share the tree; every
file written here is stamped with a ``gadget_generated: true`` frontmatter
marker, and existing files WITHOUT a gadget marker are treated as human-written
and never overwritten unless ``overwrite_human=True`` (see
``common/website_backup.py`` for the ownership rule and force backups).
"""

from __future__ import annotations

import shutil
from pathlib import Path

from common.io import atomic_write
from common.website_backup import (
    HumanContentError,
    backup_file,
    classify_file,
    record_blocked,
    stamp_generated,
)


def resolve_site_staging_root(hugo_site: Path) -> Path:
    """The site root generated files are written into: ``hugo_site`` itself.

    Relative paths are resolved against the gadget repo root (see
    :func:`common.paths.resolve_repo_path`).
    """
    from common.paths import resolve_repo_path

    return resolve_repo_path(hugo_site)


def resolve_site_content_dir(hugo_site: Path, *parts: str) -> Path:
    """Return a generated-content directory and create it if needed."""
    path = resolve_site_staging_root(hugo_site) / "content"
    if parts:
        path = path.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_site_static_dir(hugo_site: Path, *parts: str) -> Path:
    """Return a generated-static directory and create it if needed."""
    path = resolve_site_staging_root(hugo_site) / "static"
    if parts:
        path = path.joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_site_content(hugo_site: Path, relative_path: str | Path, content: str,
                       *, force: bool = False, overwrite_human: bool = False) -> Path:
    """Write a generated Hugo content file (stamped ``gadget_generated: true``).

    - An existing file without a gadget marker is human-written: raises
      :class:`HumanContentError` unless ``overwrite_human=True``.
    - ``force=True`` backs the previous file up into
      ``outputs/backups/website-force/`` before overwriting it with different
      content.
    """
    rel = Path(relative_path)
    path = resolve_site_staging_root(hugo_site) / "content" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    content = stamp_generated(content)
    if path.exists():
        if classify_file(path) == "human" and not overwrite_human:
            record_blocked(path, reason="generated output collides with human-written file")
            raise HumanContentError(
                f"Refusing to overwrite human-written file: {path}\n"
                "It has no gadget marker (or is marked gadget_generated: false). "
                "Move/rename it, or re-run with the explicit --overwrite-human opt-in."
            )
        if force:
            try:
                unchanged = path.read_text(encoding="utf-8") == content
            except (OSError, UnicodeDecodeError):
                unchanged = False
            if not unchanged:
                backup_file(path, resolve_site_staging_root(hugo_site),
                            reason="force overwrite of generated content")
    atomic_write(path, content)
    return path


def copy_site_static(hugo_site: Path, source: str | Path, relative_path: str | Path,
                     *, force: bool = False) -> Path:
    """Copy a generated static asset into ``<hugo_site>/static``.

    ``force=True`` backs up an existing target first. Static files carry no
    ownership marker, so there is no human-content block here — pipelines own
    their static namespaces (images/{daily,weekly,monthly}, benchmark-report).
    """
    src = Path(source)
    if not src.exists():
        raise FileNotFoundError(src)

    rel = Path(relative_path)
    path = resolve_site_staging_root(hugo_site) / "static" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    if force and path.exists():
        backup_file(path, resolve_site_staging_root(hugo_site),
                    reason="force overwrite of generated static asset")
    shutil.copy2(src, path)
    return path
