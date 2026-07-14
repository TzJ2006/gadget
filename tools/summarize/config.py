"""Configuration loading and resolution utilities for the summarize pipeline."""

import json
import os
import platform
from pathlib import Path
from typing import Optional


# ─── 0. 配置文件与工具函数 ─────────────────────────────────────────

# 配置文件：SUMMARIZE_CONFIG 环境变量显式指定路径（测试隔离 / 多配置切换）>
# 仓库内 tools/summarize/config.json（就在代码旁边，方便直接编辑）>
# per-user 的 ~/.config/summarize/config.json（onboard.py 写的位置）。
_REPO_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"
_HOME_CONFIG_PATH = Path.home() / ".config" / "summarize" / "config.json"


def _resolve_config_path() -> Path:
    env_path = os.environ.get("SUMMARIZE_CONFIG")
    if env_path:
        return Path(env_path).expanduser()
    return _REPO_CONFIG_PATH if _REPO_CONFIG_PATH.exists() else _HOME_CONFIG_PATH


_CONFIG_PATH = _resolve_config_path()
_cached_config: Optional[dict] = None


def _load_config() -> dict:
    """读取 ~/.config/summarize/config.json，缓存结果。"""
    global _cached_config
    if _cached_config is not None:
        return _cached_config

    if not _CONFIG_PATH.exists():
        _cached_config = {}
        return _cached_config

    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
            _cached_config = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[warn] 配置文件读取失败 ({_CONFIG_PATH}): {e}")
        _cached_config = {}

    return _cached_config


# _atomic_write imported from common.io (above)


def _resolve_output_dir(cli_value: Optional[str], env_key: str,
                        config_key: str, default: Path) -> Path:
    """按优先级解析输出目录: CLI > 环境变量 > config.json > 默认路径。"""
    if cli_value:
        return Path(cli_value).expanduser()

    env_val = os.environ.get(env_key)
    if env_val:
        return Path(env_val).expanduser()

    cfg = _load_config()
    cfg_val = cfg.get(config_key)
    if cfg_val:
        return Path(cfg_val).expanduser()

    return default


def _get_device_name() -> str:
    """从 config 读取 device_name，fallback 到 platform.node()。"""
    cfg = _load_config()
    return cfg.get("device_name") or platform.node() or "unknown"


# ─── CLI 默认值 & 环境变量桥接 ─────────────────────────────────────
# 让 `python -m summarize {auto,daily,weekly,monthly}` 从 config 读取行为，
# 一条干净的命令即可跑完整流程，无需一堆 flag。

# config key -> argparse dest。复用已有的 default_api（同一设置不再分裂来源）。
# 只放「一次设定长期生效」的行为项——不含 per-run 的 force/no_cache，也不含
# timeout（各级默认不同：daily 600 / weekly 900 / monthly 1800，单值会覆盖大的）。
_CLI_DEFAULTS_MAP = {
    "default_api": "api",
    "deploy": "deploy",
    "hugo_site": "hugo_site",
    "workers": "workers",
}


def cli_defaults() -> dict:
    """可用作 argparse 默认值的 config 值，按 dest 命名。调用方在 parse_args 前
    执行 `parser.set_defaults(**cli_defaults())` → CLI 显式参数 > config > 硬编码默认。"""
    cfg = _load_config()
    return {dest: cfg[key] for key, dest in _CLI_DEFAULTS_MAP.items() if key in cfg}


# config key -> common/ 读取的环境变量（llm 的 ollama 路径 & engine 翻译）。
_ENV_FROM_CONFIG = {
    "model": "OLLAMA_MODEL",
    "base_url": "OLLAMA_BASE_URL",
    "reasoning_effort": "OPENAI_REASONING_EFFORT",
    "translation_model": "GADGET_TRANSLATION_MODEL",
    "translation_model_ollama": "OLLAMA_TRANSLATION_MODEL",
    "translation_backend": "GADGET_TRANSLATION_BACKEND",
}


def apply_env_from_config() -> None:
    """把本地 LLM / 翻译相关旋钮从 config 灌入环境变量，使 common.llm / common.engine
    原样读取即可。ponytail: 用 setdefault 桥接环境变量，而不是把 config 对象穿过
    common/（common 不应 import tools）——真实环境变量仍然优先。"""
    cfg = _load_config()
    for key, env in _ENV_FROM_CONFIG.items():
        val = cfg.get(key)
        if val is not None:
            os.environ.setdefault(env, str(val))
