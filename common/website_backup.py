"""Ownership classification + timestamped backups for website content overwrites.

Ownership rule (single content root — generated and human posts share
``tools/website/content``):

- **generated**: the file carries a machine-readable gadget marker — either
  ``gadget_generated: true`` in frontmatter (stamped by ``write_site_content``),
  a ``gadget:src-hash:`` comment (stamped by ``write_bilingual``), or a
  ``<!-- gadget:generated -->`` comment (fallback for marker-less frontmatter).
- **human**: no gadget marker, or an explicit ``gadget_generated: false``.

Pipelines refuse to overwrite human files unless the caller passes
``overwrite_human=True`` (surfaced as a dangerous CLI opt-in). Forced
regeneration backs up the previous file into
``outputs/backups/website-force/YYYYMMDD-HHMMSS/`` with a ``manifest.json``
before overwriting. Backups are never auto-deleted.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from common.paths import GADGET_ROOT, OUTPUTS_DIR

BACKUP_ROOT = OUTPUTS_DIR / "backups" / "website-force"

GENERATED_MARKERS = (
    "gadget_generated: true",
    "gadget:src-hash:",
    "<!-- gadget:generated -->",
)
HUMAN_MARKER = "gadget_generated: false"

_FRONTMATTER_OPEN = "---\n"


class HumanContentError(RuntimeError):
    """Raised when a pipeline would overwrite a human-written file."""


def classify_content(text: str) -> str:
    """Classify markdown text as ``generated`` or ``human`` by marker."""
    if HUMAN_MARKER in text:
        return "human"
    if any(marker in text for marker in GENERATED_MARKERS):
        return "generated"
    return "human"


def classify_file(path: Path) -> str:
    """Classify a file: ``generated``, ``human``, or ``missing``.

    Unreadable/binary files classify as ``human`` — the conservative choice,
    since misclassifying human work as generated is the destructive error.
    """
    path = Path(path)
    if not path.exists():
        return "missing"
    try:
        return classify_content(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return "human"


def stamp_generated(content: str) -> str:
    """Ensure content carries a generated marker (idempotent).

    Injects ``gadget_generated: true`` into the frontmatter when present;
    otherwise appends an HTML comment marker.
    """
    if classify_content(content) == "generated" or HUMAN_MARKER in content:
        return content
    if content.startswith(_FRONTMATTER_OPEN):
        close = content.find("\n---", len(_FRONTMATTER_OPEN))
        if close != -1:
            return (content[:close] + "\ngadget_generated: true" + content[close:])
    return content.rstrip("\n") + "\n\n<!-- gadget:generated -->\n"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True,
            cwd=GADGET_ROOT, timeout=10,
        )
        return out.stdout.strip() or None
    except OSError:
        return None


_session_dir: Path | None = None  # one timestamped backup dir per process


def _backup_session_dir() -> Path:
    global _session_dir
    if _session_dir is None:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        candidate = BACKUP_ROOT / stamp
        n = 1
        while candidate.exists():
            candidate = BACKUP_ROOT / f"{stamp}-{n}"
            n += 1
        candidate.mkdir(parents=True)
        candidate.joinpath("manifest.json").write_text(
            json.dumps({
                "created": datetime.now().isoformat(timespec="seconds"),
                "command": " ".join(sys.argv),
                "git_commit": _git_commit(),
                "files": [],
            }, indent=2), encoding="utf-8")
        _session_dir = candidate
    return _session_dir


def _append_manifest(entry: dict) -> None:
    manifest_path = _backup_session_dir() / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"].append(entry)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                             encoding="utf-8")


def backup_file(target: Path, site_root: Path, *, reason: str,
                action: str = "overwritten") -> Path | None:
    """Back up ``target`` (if it exists) before an overwrite.

    Directory structure under ``site_root`` (content/... or static/...) is
    preserved inside the timestamped backup dir. Returns the backup path.
    """
    import shutil

    target = Path(target)
    if not target.exists():
        return None
    try:
        rel = target.resolve().relative_to(Path(site_root).resolve())
    except ValueError:
        rel = Path(target.name)
    session = _backup_session_dir()
    dest = session / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(target, dest)
    _append_manifest({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "original_path": str(target),
        "target_path": str(target),
        "backup_path": rel.as_posix(),
        "sha256": _sha256(dest),
        "size": dest.stat().st_size,
        "ownership": classify_file(dest),
        "action": action,
        "reason": reason,
    })
    return dest


def record_blocked(target: Path, *, reason: str) -> None:
    """Record a collision-blocked overwrite attempt in the session manifest."""
    target = Path(target)
    _append_manifest({
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "original_path": str(target),
        "target_path": str(target),
        "backup_path": None,
        "sha256": _sha256(target) if target.exists() else None,
        "size": target.stat().st_size if target.exists() else None,
        "ownership": classify_file(target),
        "action": "collision-blocked",
        "reason": reason,
    })
