"""Configuration management for the research tool.

Reads/writes the ``research`` section of the repo-root ``config.json``
(via ``common.config``). Override path with ``GADGET_CONFIG``.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from common import config as gadget_config

# Keep in sync with research.apis.semantic_scholar.DEFAULT_TOP_VENUES.
DEFAULT_TOP_VENUES: list[str] = [
    "icra", "iros", "rss", "corl",
    "neurips", "nips", "icml", "iclr",
    "cvpr", "iccv", "eccv",
    "aaai", "ijcai",
    "ral", "t-ro",
    "science robotics",
]

DEFAULT_WEIGHTS: dict[str, float] = {
    "h_index": 25,
    "total_citations": 20,
    "recent_citations": 20,
    "top_venue_ratio": 20,
    "career_stage": 15,
}

DEFAULT_TIER_CUTOFFS: dict[str, float] = {
    "leader": 75,
    "rising": 50,
    "active": 30,
}

DEFAULT_STUDENT_THRESHOLD = 0.4

DEFAULT_STUDENT_WEIGHTS: dict[str, float] = {
    "first_author": 0.4,
    "time_concentration": 0.25,
    "frequency": 0.2,
    "recency": 0.15,
}

DEFAULT_SCORING: dict[str, Any] = {
    "top_venues": list(DEFAULT_TOP_VENUES),
    "weights": dict(DEFAULT_WEIGHTS),
    "tier_cutoffs": dict(DEFAULT_TIER_CUTOFFS),
    "student_threshold": DEFAULT_STUDENT_THRESHOLD,
    "student_weights": dict(DEFAULT_STUDENT_WEIGHTS),
}

DEFAULT_CONFIG: dict[str, Any] = {
    "model": "sonnet",
    "default_mode": "fast",
    "default_depth": 1,
    "max_students": 10,
    "output_dir": "",  # Empty means use project default
    "semantic_scholar_api_key": "",
    "scoring": copy.deepcopy(DEFAULT_SCORING),
}

# Back-compat aliases (path is the unified root file).
DEFAULT_CONFIG_PATH = gadget_config.DEFAULT_CONFIG_PATH
DEFAULT_CONFIG_DIR = DEFAULT_CONFIG_PATH.parent


def _merge_scoring(override: Any) -> dict[str, Any]:
    """Deep-merge a partial ``scoring`` dict onto defaults. Missing keys stay default."""
    merged = copy.deepcopy(DEFAULT_SCORING)
    if not isinstance(override, dict):
        return merged
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        elif value is not None:
            merged[key] = value
    return merged


def _fresh_defaults() -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    config["scoring"] = copy.deepcopy(DEFAULT_SCORING)
    return config


def _overlay_research(config: dict[str, Any], stored: dict[str, Any]) -> None:
    scoring_in = stored.get("scoring")
    for key, value in stored.items():
        if key == "scoring":
            continue
        config[key] = value
    config["scoring"] = _merge_scoring(scoring_in)


def _apply_top_venues(scoring: dict[str, Any]) -> None:
    venues = scoring.get("top_venues")
    if not isinstance(venues, (list, tuple, set)):
        return
    from research.apis.semantic_scholar import set_top_venues
    set_top_venues(venues)


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load research section from disk, falling back to defaults.

    If *config_path* is given (tests), read that file's ``research`` section,
    or treat a flat dict as the section itself.
    Applies ``research.scoring.top_venues`` via ``set_top_venues``.
    """
    config = _fresh_defaults()
    if config_path is not None:
        import json
        if config_path.exists():
            with open(config_path, encoding="utf-8") as f:
                stored = json.load(f)
            if isinstance(stored.get("research"), dict):
                _overlay_research(config, stored["research"])
            elif isinstance(stored, dict):
                _overlay_research(config, stored)
        _apply_top_venues(config["scoring"])
        return config

    _overlay_research(config, gadget_config.load_section("research"))
    _apply_top_venues(config["scoring"])
    return config


def scoring_config(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return merged ``research.scoring`` (defaults filled in)."""
    if config is None:
        config = load_config()
    scoring = config.get("scoring")
    if isinstance(scoring, dict):
        return scoring
    return copy.deepcopy(DEFAULT_SCORING)


def save_config(config: dict[str, Any], config_path: Path | None = None) -> None:
    """Save research section to the unified root config (or *config_path* for tests)."""
    if config_path is not None:
        import json
        from common.io import atomic_write
        config_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(config_path, json.dumps(config, indent=2, ensure_ascii=False) + "\n")
        return

    gadget_config.update_section("research", config, replace=True)


def interactive_config_init() -> dict[str, Any]:
    """Interactive config setup."""
    print("=== 研究者分析工具 — 配置初始化 ===\n")
    print(f"写入: {gadget_config.resolve_config_path()}  (section: research)\n")
    config = load_config()

    model = input(f"默认 Claude 模型 [sonnet/opus/haiku] (当前: {config['model']}): ").strip()
    if model in ("sonnet", "opus", "haiku"):
        config["model"] = model

    mode = input(f"默认分析模式 [fast/detailed] (当前: {config['default_mode']}): ").strip()
    if mode in ("fast", "detailed"):
        config["default_mode"] = mode

    depth = input(f"默认递归深度 [0-3] (当前: {config['default_depth']}): ").strip()
    if depth.isdigit() and 0 <= int(depth) <= 3:
        config["default_depth"] = int(depth)

    max_stu = input(f"每层最多探索学生数 (当前: {config['max_students']}): ").strip()
    if max_stu.isdigit() and int(max_stu) > 0:
        config["max_students"] = int(max_stu)

    cur_out = config.get("output_dir") or "(默认)"
    out_dir = input(f"输出目录 (可选, 回车保留当前: {cur_out}): ").strip()
    if out_dir:
        config["output_dir"] = out_dir

    s2_key = input("Semantic Scholar API Key (可选, 回车跳过): ").strip()
    if s2_key:
        config["semantic_scholar_api_key"] = s2_key

    save_config(config)
    print(f"\n配置已保存到 {gadget_config.resolve_config_path()} (section: research)")
    return config


def show_config(config: dict[str, Any]) -> None:
    """Display current configuration."""
    print("=== 当前配置 ===")
    print(f"文件: {gadget_config.resolve_config_path()} (section: research)")
    labels = {
        "model": "Claude 模型",
        "default_mode": "默认模式",
        "default_depth": "递归深度",
        "max_students": "最大学生数",
        "output_dir": "输出目录",
        "semantic_scholar_api_key": "S2 API Key",
    }
    for key, label in labels.items():
        val = config.get(key, "")
        if key == "semantic_scholar_api_key" and val:
            val = val[:8] + "..."
        if val == "" or val is None:
            val = "(默认)" if key == "output_dir" else "(未设置)"
        print(f"  {label}: {val}")
    scoring = config.get("scoring") if isinstance(config.get("scoring"), dict) else {}
    cutoffs = scoring.get("tier_cutoffs") if isinstance(scoring.get("tier_cutoffs"), dict) else {}
    print(f"  评分权重: {scoring.get('weights', '(默认)')}")
    print(
        f"  档位阈值: leader={cutoffs.get('leader', 75)} "
        f"rising={cutoffs.get('rising', 50)} active={cutoffs.get('active', 30)}"
    )
    print(f"  学生阈值: {scoring.get('student_threshold', 0.4)}")
    venues = scoring.get("top_venues") or []
    print(f"  顶会数: {len(venues)}")


def resolve_output_dir(config: dict[str, Any]) -> Path:
    """Resolve the output directory."""
    from common.paths import DATA_DIR, resolve_repo_path

    custom = config.get("output_dir", "")
    if custom:
        return resolve_repo_path(custom)
    return DATA_DIR / "research"


def resolve_profiler_paths(config: dict[str, Any]) -> dict[str, Path]:
    """Resolve profiler output paths split across the unified outputs/ tree."""
    from common.paths import REPORTS_DIR, CACHE_DIR, DATA_DIR, resolve_repo_path

    custom = config.get("output_dir", "")
    if custom:
        root = resolve_repo_path(custom)
        return {
            "profiles": root / "profiles",
            "reports": root / "reports",
            "cache": root / ".cache",
        }
    return {
        "profiles": DATA_DIR / "research-profiler" / "profiles",
        "reports": REPORTS_DIR / "research-profiler",
        "cache": CACHE_DIR / "research-profiler",
    }
