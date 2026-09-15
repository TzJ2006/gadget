"""Pipeline-generated Hugo paths, relative to content/.

Deploy pipelines write complete bilingual pairs here (gadget_generated /
gadget:src-hash). Translation and preflight skip them so src-hash markers
stay in sync. Override with translate_site_batch --include-generated.

This is a fast path-shaped guess, not the ownership answer — that comes from
the gadget_generated marker in the file itself. It exists to avoid reading a
few thousand files.
"""

from __future__ import annotations

from pathlib import Path

GENERATED_CONTENT_DIRS = (
    "bugJournal/daily",
    "bugJournal/weekly",
    "bugJournal/monthly",
    "research",
)
GENERATED_CONTENT_FILES = ("benchmark.md", "benchmark.zh.md")


def is_generated_relpath(rel: str) -> bool:
    """Is this content-relative path one the pipeline generates?

    One matcher for every consumer, because they had three. In particular the
    file list means exact relative paths -- content/benchmark.md -- not every
    file anywhere called benchmark.md. publish.py matched on the bare filename,
    so a hand-written content/posts/benchmark.md counted as generated there and
    as hand-written in preflight, and the publish step silently skipped
    rewriting its stale ../../static links.
    """
    rel = rel.lstrip("./")
    if rel in GENERATED_CONTENT_FILES:
        return True
    return any(rel == d or rel.startswith(d + "/") for d in GENERATED_CONTENT_DIRS)


def is_generated_path(path: Path, content_root: Path) -> bool:
    """Same question for an absolute path, given the content/ root."""
    try:
        rel = Path(path).resolve().relative_to(Path(content_root).resolve())
    except (ValueError, OSError):
        return False
    return is_generated_relpath(rel.as_posix())
