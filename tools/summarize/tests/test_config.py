"""Tests for summarize.config — configuration loading and resolution."""

import json
import platform

import pytest

import summarize.config as config_mod
from common import config as gadget_config
from summarize.config import (
    _load_config,
    _resolve_output_dir,
    _get_device_name,
    cli_defaults,
    apply_env_from_config,
)


def _write_summarize(tmp_path, monkeypatch, section: dict) -> None:
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"summarize": section}), encoding="utf-8")
    monkeypatch.setenv("GADGET_CONFIG", str(path))
    gadget_config.clear_cache()


@pytest.fixture(autouse=True)
def _reset_cache(tmp_path, monkeypatch):
    """Point GADGET_CONFIG at an isolated temp file; clear caches; restore env."""
    import os
    saved = {k: os.environ.get(k) for k in config_mod._ENV_FROM_CONFIG.values()}
    path = tmp_path / "config.json"
    monkeypatch.setenv("GADGET_CONFIG", str(path))
    gadget_config.clear_cache()
    yield
    gadget_config.clear_cache()
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# ── _load_config ──────────────────────────────────────────────────────


def test_load_config_no_file(tmp_path, monkeypatch):
    """When the config file does not exist, _load_config returns an empty dict."""
    monkeypatch.setenv("GADGET_CONFIG", str(tmp_path / "nonexistent" / "config.json"))
    gadget_config.clear_cache()
    assert _load_config() == {}


def test_load_config_caches(tmp_path, monkeypatch):
    """Calling _load_config twice returns the same section contents."""
    _write_summarize(tmp_path, monkeypatch, {"device_name": "test-box"})
    first = _load_config()
    second = _load_config()
    assert first == second == {"device_name": "test-box"}


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
    _write_summarize(tmp_path, monkeypatch, {"test_dir": str(tmp_path / "cfg_output")})

    result = _resolve_output_dir(
        cli_value=None,
        env_key="SUMMARIZE_TEST_DIR",
        config_key="test_dir",
        default=tmp_path / "default",
    )
    assert result == env_dir


def test_resolve_output_dir_default(tmp_path, monkeypatch):
    """When nothing is set, returns the default path."""
    monkeypatch.setenv("GADGET_CONFIG", str(tmp_path / "no_such_config.json"))
    gadget_config.clear_cache()
    default = tmp_path / "default_output"
    result = _resolve_output_dir(
        cli_value=None,
        env_key="SUMMARIZE_NONEXISTENT_VAR",
        config_key="nonexistent_key",
        default=default,
    )
    assert result == default


# ── _get_device_name ─────────────────────────────────────────────────


def test_get_device_name_from_config(tmp_path, monkeypatch):
    """Returns device_name from config when present."""
    _write_summarize(tmp_path, monkeypatch, {"device_name": "my-desktop"})
    assert _get_device_name() == "my-desktop"


def test_get_device_name_fallback(tmp_path, monkeypatch):
    """Falls back to platform.node() when config has no device_name."""
    monkeypatch.setenv("GADGET_CONFIG", str(tmp_path / "no_config.json"))
    gadget_config.clear_cache()
    assert _get_device_name() == (platform.node() or "unknown")


# ── cli_defaults ─────────────────────────────────────────────────────


def test_cli_defaults_maps_keys(tmp_path, monkeypatch):
    """Maps config keys to argparse dests; absent keys are omitted."""
    _write_summarize(tmp_path, monkeypatch, {
        "default_api": "ollama",
        "deploy": True,
        "workers": 4,
        "device_name": "ignored",
    })
    assert cli_defaults() == {"api": "ollama", "deploy": True, "workers": 4}


def test_cli_defaults_empty_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setenv("GADGET_CONFIG", str(tmp_path / "nope.json"))
    gadget_config.clear_cache()
    assert cli_defaults() == {}


def test_cli_defaults_feeds_argparse(tmp_path, monkeypatch):
    """set_defaults(**cli_defaults()) drives the parser; CLI flag still wins."""
    import argparse

    _write_summarize(tmp_path, monkeypatch, {"default_api": "ollama"})
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="claude_cli")
    parser.set_defaults(**cli_defaults())

    assert parser.parse_args([]).api == "ollama"
    assert parser.parse_args(["--api", "openai"]).api == "openai"


# ── apply_env_from_config ────────────────────────────────────────────


def test_apply_env_from_config_sets_env(tmp_path, monkeypatch):
    """Config LLM knobs are bridged to env vars."""
    _write_summarize(tmp_path, monkeypatch, {
        "model": "qwen3.6-sum",
        "reasoning_effort": "none",
    })
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)

    apply_env_from_config()

    import os
    assert os.environ["OLLAMA_MODEL"] == "qwen3.6-sum"
    assert os.environ["OPENAI_REASONING_EFFORT"] == "none"


def test_apply_env_from_config_does_not_override(tmp_path, monkeypatch):
    """A pre-set env var wins over config (setdefault semantics)."""
    _write_summarize(tmp_path, monkeypatch, {"model": "from-config"})
    monkeypatch.setenv("OLLAMA_MODEL", "from-env")

    apply_env_from_config()

    import os
    assert os.environ["OLLAMA_MODEL"] == "from-env"
