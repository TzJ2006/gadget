"""Configuration management for the research tool."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "research"
DEFAULT_CONFIG_PATH = DEFAULT_CONFIG_DIR / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "model": "sonnet",
    "default_mode": "fast",
    "default_depth": 1,
    "max_students": 10,
    "output_dir": "",  # Empty means use project default
    "semantic_scholar_api_key": "",
}


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load config from disk, falling back to defaults."""
    path = config_path or DEFAULT_CONFIG_PATH
    config = dict(DEFAULT_CONFIG)
    if path.exists():
        with open(path) as f:
            stored = json.load(f)
        config.update(stored)
    return config


def save_config(config: dict[str, Any], config_path: Path | None = None) -> None:
    """Save config to disk."""
    path = config_path or DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def interactive_config_init() -> dict[str, Any]:
    """Interactive config setup."""
    print("=== 研究者分析工具 — 配置初始化 ===\n")
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
    print(f"\n配置已保存到 {DEFAULT_CONFIG_PATH}")
    return config


def show_config(config: dict[str, Any]) -> None:
    """Display current configuration."""
    print("=== 当前配置 ===")
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


def resolve_output_dir(config: dict[str, Any]) -> Path:
    """Resolve the output directory."""
    custom = config.get("output_dir", "")
    if custom:
        return Path(custom)
    from common.paths import DATA_DIR
    return DATA_DIR / "research"


def resolve_profiler_paths(config: dict[str, Any]) -> dict[str, Path]:
    """Resolve profiler output paths split across the unified outputs/ tree."""
    from common.paths import REPORTS_DIR, CACHE_DIR, DATA_DIR

    custom = config.get("output_dir", "")
    if custom:
        root = Path(custom)
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
