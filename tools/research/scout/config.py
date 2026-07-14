"""Unified configuration for Research Scout and Researcher Profiler.

Loads from two config paths with fallback:
  1. ~/.config/research_scout/config.json  (Scout primary)
  2. ~/.config/research/config.json         (Profiler fallback)

Resolution order for parameters: CLI flag > project.json > merged config > hardcoded default.
"""

from __future__ import annotations

import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

from common.paths import (
    GADGET_ROOT,
    TOOLS_DIR,
    REPORTS_DIR as _REPORTS_BASE,
    CACHE_DIR as _CACHE_BASE,
    LOGS_DIR as _LOGS_BASE,
)

# ─── Path constants (derived from common.paths, NOT __file__) ────────

PROJECTS_DIR = TOOLS_DIR / "research" / "projects"

REPORTS_DIR = _REPORTS_BASE / "research-scout"
CACHE_DIR = _CACHE_BASE / "research-scout"
EVAL_CACHE_DIR = CACHE_DIR / "eval"
PAPERS_CACHE_DIR = CACHE_DIR / "papers"
LOGS_DIR = _LOGS_BASE / "research-scout"

DEFAULT_HUGO_SITE = TOOLS_DIR / "website"

# ─── Tunable defaults ────────────────────────────────────────────────

DEFAULT_LOOKBACK_DAYS = 7
MAX_PAPERS_PER_PROJECT = 50
TOP_PAPERS_IN_REPORT = 5
MAX_HIGH_RELEVANCE = 20
DEFAULT_LANGUAGE = "zh"
BIORXIV_MAX_PAGES = 10
INSIGHT_TOP_N = 3
MAX_FULLTEXT_CHARS = 40000
INSIGHT_CACHE_DIR = CACHE_DIR / "insight"

# ─── Config file paths ──────────────────────────────────────────────

_SCOUT_CONFIG_PATH = Path.home() / ".config" / "research_scout" / "config.json"
_PROFILER_CONFIG_PATH = Path.home() / ".config" / "research" / "config.json"

_cached_config: Optional[dict] = None


def load_scout_config() -> dict:
    """Load merged config: Scout primary, Profiler fallback for missing keys.

    Cached after first call. Reads both config files and merges them
    (Scout keys take precedence).
    """
    global _cached_config
    if _cached_config is not None:
        return _cached_config

    scout_cfg: dict = {}
    profiler_cfg: dict = {}

    for path, target in [(_SCOUT_CONFIG_PATH, scout_cfg), (_PROFILER_CONFIG_PATH, profiler_cfg)]:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    target.update(json.load(f))
            except (OSError, json.JSONDecodeError) as e:
                get_logger().warning("Failed to load config %s: %s", path, e)

    # Merge: scout takes precedence, profiler fills gaps
    merged = {**profiler_cfg, **scout_cfg}
    _cached_config = merged
    return _cached_config


def resolve_param(args, project, param_name: str, hardcoded_default):
    """Resolve parameter priority: CLI flag > project.json > config.json > hardcoded default."""
    cli_val = getattr(args, param_name, None) if args else None
    if cli_val is not None:
        return cli_val
    if project and project.get(param_name) is not None:
        return project[param_name]
    cfg = load_scout_config()
    return cfg.get(f"default_{param_name}", hardcoded_default)


def get_hugo_site(args) -> Path:
    """Resolve Hugo site path from CLI args or config."""
    cli_val = getattr(args, "hugo_site", None)
    if cli_val:
        return Path(cli_val)
    cfg = load_scout_config()
    if cfg.get("hugo_site"):
        return Path(cfg["hugo_site"]).expanduser()
    return DEFAULT_HUGO_SITE


def get_reports_dir(args) -> Path:
    """Resolve reports output directory."""
    cli_val = getattr(args, "reports_dir", None)
    if cli_val:
        return Path(cli_val)
    cfg = load_scout_config()
    if cfg.get("reports_dir"):
        return Path(cfg["reports_dir"]).expanduser()
    return REPORTS_DIR


# ─── Logging ─────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    """Set up logging: stdout (INFO) + rotating file (DEBUG, 5MB x 3)."""
    log = logging.getLogger("research_scout")
    if log.handlers:
        return log  # Already initialized

    log.setLevel(logging.DEBUG)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    log.addHandler(console)

    # File handler
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(
        LOGS_DIR / "research_scout.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(funcName)s: %(message)s"
    ))
    log.addHandler(fh)

    return log


def get_logger() -> logging.Logger:
    """Get the shared 'research_scout' logger instance."""
    return logging.getLogger("research_scout")
