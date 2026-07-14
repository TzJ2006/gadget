"""Unified gadget config — single repo-root ``config.json`` for all tools.

Resolution (fail-fast — no ``~/.config/...`` or per-tool legacy paths):

  ``GADGET_CONFIG`` env (explicit path; tests / multi-config) →
  ``<GADGET_ROOT>/config.json``

Schema is namespaced by tool section::

  {
    "summarize": { ... },
    "research": { ... },
    "research_scout": { ... },
    "sync": { ... },
    "translator": { "models": [...] }
  }

Missing file or section → ``{}`` (callers apply their own defaults).
Tracked template: ``config.example.json`` at the repo root.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from common.io import atomic_write
from common.paths import GADGET_ROOT

EXAMPLE_CONFIG_PATH = GADGET_ROOT / "config.example.json"
DEFAULT_CONFIG_PATH = GADGET_ROOT / "config.json"

_cached_root: Optional[dict[str, Any]] = None
_cached_path: Optional[Path] = None


def resolve_config_path() -> Path:
    """Return the active config path (env override or repo-root ``config.json``)."""
    env_path = os.environ.get("GADGET_CONFIG")
    if env_path:
        return Path(env_path).expanduser()
    return DEFAULT_CONFIG_PATH


def clear_cache() -> None:
    """Drop the in-memory root-config cache (after writes or in tests)."""
    global _cached_root, _cached_path
    _cached_root = None
    _cached_path = None


def load_root_config() -> dict[str, Any]:
    """Load the full root config dict. Missing/unreadable file → ``{}``."""
    global _cached_root, _cached_path
    path = resolve_config_path()
    if _cached_root is not None and _cached_path == path:
        return _cached_root

    if not path.exists():
        _cached_root = {}
        _cached_path = path
        return _cached_root

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        _cached_root = data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError) as e:
        print(f"[warn] config read failed ({path}): {e}")
        _cached_root = {}

    _cached_path = path
    return _cached_root


def load_section(section: str) -> dict[str, Any]:
    """Return one top-level section as a dict (missing → ``{}``)."""
    root = load_root_config()
    val = root.get(section)
    return dict(val) if isinstance(val, dict) else {}


def save_root_config(root: dict[str, Any], *, path: Path | None = None) -> Path:
    """Atomically write the full root config and refresh the cache."""
    target = path or resolve_config_path()
    atomic_write(target, json.dumps(root, ensure_ascii=False, indent=2) + "\n")
    clear_cache()
    # Prime cache so immediate reads see what we wrote
    global _cached_root, _cached_path
    _cached_root = dict(root)
    _cached_path = target
    return target


def update_section(section: str, data: dict[str, Any], *, replace: bool = False) -> Path:
    """Merge (default) or replace *data* into ``root[section]`` and save.

    Returns the path written.
    """
    root = dict(load_root_config())
    if replace:
        root[section] = dict(data)
    else:
        existing = root.get(section)
        base = dict(existing) if isinstance(existing, dict) else {}
        base.update(data)
        root[section] = base
    return save_root_config(root)


def config_path() -> Path:
    """Alias for :func:`resolve_config_path` (display / existence checks)."""
    return resolve_config_path()
