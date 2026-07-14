"""SHA-256 disk cache for API results and LLM analysis."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from common.io import atomic_write, content_hash


class DiskCache:
    """Simple disk-based cache with optional TTL."""

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key_hash(self, key: str) -> str:
        return content_hash(key)

    def _path_for(self, namespace: str, key: str, ensure_dir: bool = False) -> Path:
        ns_dir = self.cache_dir / namespace
        if ensure_dir:
            ns_dir.mkdir(parents=True, exist_ok=True)
        return ns_dir / f"{self._key_hash(key)}.json"

    def get(self, namespace: str, key: str, ttl_seconds: int | None = None) -> Any | None:
        """Retrieve from cache. Returns None on miss or expiry."""
        path = self._path_for(namespace, key)
        if not path.exists():
            return None
        try:
            with open(path) as f:
                entry = json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

        if ttl_seconds is not None:
            stored_at = entry.get("_cached_at", 0)
            if time.time() - stored_at > ttl_seconds:
                return None

        return entry.get("data")

    def put(self, namespace: str, key: str, data: Any) -> None:
        """Store data in cache."""
        path = self._path_for(namespace, key, ensure_dir=True)
        entry = {
            "_cached_at": time.time(),
            "_key": key,
            "data": data,
        }
        atomic_write(path, json.dumps(entry, ensure_ascii=False, indent=2))

    def has(self, namespace: str, key: str, ttl_seconds: int | None = None) -> bool:
        return self.get(namespace, key, ttl_seconds) is not None

    def clear_namespace(self, namespace: str) -> int:
        """Remove all entries in a namespace. Returns count removed."""
        ns_dir = self.cache_dir / namespace
        if not ns_dir.exists():
            return 0
        count = 0
        for f in ns_dir.glob("*.json"):
            f.unlink()
            count += 1
        return count
