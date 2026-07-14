"""Shared I/O utilities — atomic writes, content hashing, config loading."""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Optional


def atomic_write(path: Path, data: str) -> None:
    """Write *data* to *path* atomically via temp file + rename."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def content_hash(text: str, length: int = 16) -> str:
    """Return the first *length* hex chars of the SHA-256 digest of *text*."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def load_json_config(path: Path, cache: Optional[dict] = None) -> dict:
    """Load a JSON config file. Returns {} on missing file or parse error.

    If *cache* dict is provided, results are memoized under *str(path)*.
    """
    key = str(path)
    if cache is not None and key in cache:
        return cache[key]

    if not Path(path).exists():
        result: dict = {}
    else:
        try:
            with open(path, "r", encoding="utf-8") as f:
                result = json.load(f)
        except (OSError, json.JSONDecodeError):
            result = {}

    if cache is not None:
        cache[key] = result
    return result
