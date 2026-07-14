"""Tests for summarize.config — configuration loading and resolution."""

import json
import platform
from pathlib import Path
from unittest.mock import patch

import pytest

import summarize.config as config_mod
from summarize.config import (
    _load_config,
    _resolve_output_dir,
    _get_device_name,
    cli_defaults,
    apply_env_from_config,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    """Clear the config cache and restore bridged env vars around each test.

    apply_env_from_config() writes via os.environ.setdefault; snapshot+restore the
    target vars so a test that sets one (from an absent baseline) can't leak it into
    later tests — notably the e2e subprocess, which inherits os.environ.
    """
    import os
    saved = {k: os.environ.get(k) for k in config_mod._ENV_FROM_CONFIG.values()}
    config_mod._cached_config = None
    yield
    config_mod._cached_config = None
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ── _load_config ──────────────────────────────────────────────────────


def test_load_config_no_file(tmp_path):
    """When the config file does not exist, _load_config returns an empty dict."""
    fake_path = tmp_path / "nonexistent" / "config.json"
    with patch.object(config_mod, "_CONFIG_PATH", fake_path):
        result = _load_config()
    assert result == {}


def test_load_config_caches(tmp_path):
    """Calling _load_config twice returns the exact same cached object."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"device_name": "test-box"}), encoding="utf-8")

    with patch.object(config_mod, "_CONFIG_PATH", cfg_file):
        first = _load_config()
        second = _load_config()

    assert first is second
    assert first == {"device_name": "test-box"}


# ── _resolve_output_dir ──────────────────────────────────────────────


def test_resolve_output_dir_cli_priority(tmp_path):
    """CLI value takes highest priority over env, config, and default."""
    cli_dir = tmp_path / "cli_output"
    result = _resolve_output_dir(
        cli_value=str(cli_dir),
        env_key="SUMMARIZE_FAKE_DIR",
        config_key="fake_dir",
        default=tmp_path / "default",
    )
    assert result == cli_dir


def test_resolve_output_dir_env_priority(tmp_path, monkeypatch):
    """Environment variable takes priority over config and default."""
    env_dir = tmp_path / "env_output"
    monkeypatch.setenv("SUMMARIZE_TEST_DIR", str(env_dir))

    # Ensure config also has a value (should be ignored)
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"test_dir": str(tmp_path / "cfg_output")}), encoding="utf-8")

    with patch.object(config_mod, "_CONFIG_PATH", cfg_file):
        result = _resolve_output_dir(
            cli_value=None,
            env_key="SUMMARIZE_TEST_DIR",
            config_key="test_dir",
            default=tmp_path / "default",
        )

    assert result == env_dir


def test_resolve_output_dir_default(tmp_path):
    """When nothing is set, returns the default path."""
    fake_cfg = tmp_path / "no_such_config.json"
    default = tmp_path / "default_output"

    with patch.object(config_mod, "_CONFIG_PATH", fake_cfg):
        result = _resolve_output_dir(
            cli_value=None,
            env_key="SUMMARIZE_NONEXISTENT_VAR",
            config_key="nonexistent_key",
            default=default,
        )

    assert result == default


# ── _get_device_name ─────────────────────────────────────────────────


def test_get_device_name_from_config(tmp_path):
    """Returns device_name from config when present."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"device_name": "my-desktop"}), encoding="utf-8")

    with patch.object(config_mod, "_CONFIG_PATH", cfg_file):
        name = _get_device_name()

    assert name == "my-desktop"


def test_get_device_name_fallback(tmp_path):
    """Falls back to platform.node() when config has no device_name."""
    fake_cfg = tmp_path / "no_config.json"

    with patch.object(config_mod, "_CONFIG_PATH", fake_cfg):
        name = _get_device_name()

    assert name == (platform.node() or "unknown")


# ── cli_defaults ─────────────────────────────────────────────────────


def test_cli_defaults_maps_keys(tmp_path):
    """Maps config keys to argparse dests; absent keys are omitted."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "default_api": "ollama",
        "deploy": True,
        "workers": 4,
        "device_name": "ignored",  # not a CLI default → dropped
    }), encoding="utf-8")

    with patch.object(config_mod, "_CONFIG_PATH", cfg_file):
        d = cli_defaults()

    assert d == {"api": "ollama", "deploy": True, "workers": 4}


def test_cli_defaults_empty_when_no_file(tmp_path):
    with patch.object(config_mod, "_CONFIG_PATH", tmp_path / "nope.json"):
        assert cli_defaults() == {}


def test_cli_defaults_feeds_argparse(tmp_path):
    """set_defaults(**cli_defaults()) drives the parser; CLI flag still wins."""
    import argparse

    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"default_api": "ollama"}), encoding="utf-8")

    with patch.object(config_mod, "_CONFIG_PATH", cfg_file):
        parser = argparse.ArgumentParser()
        parser.add_argument("--api", default="claude_cli")
        parser.set_defaults(**cli_defaults())

        assert parser.parse_args([]).api == "ollama"            # config beats hardcoded
        assert parser.parse_args(["--api", "openai"]).api == "openai"  # CLI beats config


# ── apply_env_from_config ────────────────────────────────────────────


def test_apply_env_from_config_sets_env(tmp_path, monkeypatch):
    """Config LLM knobs are bridged to env vars."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({
        "model": "qwen3.6-sum",
        "reasoning_effort": "none",
    }), encoding="utf-8")
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)

    with patch.object(config_mod, "_CONFIG_PATH", cfg_file):
        apply_env_from_config()

    import os
    assert os.environ["OLLAMA_MODEL"] == "qwen3.6-sum"
    assert os.environ["OPENAI_REASONING_EFFORT"] == "none"


def test_apply_env_from_config_does_not_override(tmp_path, monkeypatch):
    """A pre-set env var wins over config (setdefault semantics)."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"model": "from-config"}), encoding="utf-8")
    monkeypatch.setenv("OLLAMA_MODEL", "from-env")

    with patch.object(config_mod, "_CONFIG_PATH", cfg_file):
        apply_env_from_config()

    import os
    assert os.environ["OLLAMA_MODEL"] == "from-env"
