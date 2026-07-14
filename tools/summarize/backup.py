"""Backup existing report files before they are overwritten (e.g. --force reruns).

Copies go to outputs/backups/summarize/, named <stem>.<mtime-stamp><suffix>.
The mtime stamp dedupes naturally: the same file version is only backed up once.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from common.paths import OUTPUTS_DIR

BACKUP_DIR = OUTPUTS_DIR / "backups" / "summarize"


def backup_existing(*paths) -> list[Path]:
    """Copy each existing path into BACKUP_DIR; return the backup paths made."""
    saved = []
    for p in paths:
        p = Path(p)
        if not p.exists():
            continue
        stamp = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y%m%d-%H%M%S")
        dest = BACKUP_DIR / f"{p.stem}.{stamp}{p.suffix}"
        if dest.exists():
            continue
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
        print(f"[ok] Backed up {p.name} -> {dest}")
        saved.append(dest)
    return saved
