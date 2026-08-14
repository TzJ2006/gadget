"""Tests for common.config — unified repo-root config.json."""

import json
import subprocess
import sys

import pytest

from common import config as gadget_config


@pytest.fixture(autouse=True)
def _isolate_config(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    monkeypatch.setenv("GADGET_CONFIG", str(path))
    gadget_config.clear_cache()
    yield path
    gadget_config.clear_cache()


def test_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("GADGET_CONFIG", str(tmp_path / "missing.json"))
    gadget_config.clear_cache()
    assert gadget_config.load_root_config() == {}
    assert gadget_config.load_section("summarize") == {}


def test_load_section_and_update(_isolate_config):
    path = _isolate_config
    gadget_config.update_section("summarize", {"device_name": "box"}, replace=True)
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "summarize": {"device_name": "box"},
    }
    assert gadget_config.load_section("summarize") == {"device_name": "box"}


def test_update_section_merges(_isolate_config):
    gadget_config.update_section("summarize", {"device_name": "a", "workers": 2})
    gadget_config.update_section("summarize", {"workers": 4})
    assert gadget_config.load_section("summarize") == {
        "device_name": "a",
        "workers": 4,
    }


def test_sections_are_independent(_isolate_config):
    gadget_config.update_section("summarize", {"device_name": "pc"})
    gadget_config.update_section("sync", {"rclone_remote": "gdrive:gadget"})
    root = gadget_config.load_root_config()
    assert set(root) == {"summarize", "sync"}
    assert root["summarize"]["device_name"] == "pc"
    assert root["sync"]["rclone_remote"] == "gdrive:gadget"


def test_cache_invalidates_on_clear(_isolate_config):
    path = _isolate_config
    path.write_text(json.dumps({"summarize": {"device_name": "first"}}), encoding="utf-8")
    gadget_config.clear_cache()
    assert gadget_config.load_section("summarize")["device_name"] == "first"
    path.write_text(json.dumps({"summarize": {"device_name": "second"}}), encoding="utf-8")
    # still cached
    assert gadget_config.load_section("summarize")["device_name"] == "first"
    gadget_config.clear_cache()
    assert gadget_config.load_section("summarize")["device_name"] == "second"


def test_no_config_path_alias():
    assert not hasattr(gadget_config, "config_path")


def test_from_common_import_config_skips_engines():
    """Package import of config must not load llm/engine/translation/hugo."""
    script = """\
import sys
from common import config
from common.config import resolve_config_path, load_section
heavy = {"common.llm", "common.engine", "common.translation", "common.hugo"}
loaded = sorted(heavy & set(sys.modules))
assert not loaded, loaded
assert callable(config.resolve_config_path)
assert callable(resolve_config_path)
assert callable(load_section)
assert not hasattr(config, "config_path")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_from_common_import_submodules():
    """Lazy package init still allows ``from common import llm|engine|translation``."""
    script = """\
from common import llm, engine, translation
assert hasattr(llm, "call_llm")
assert hasattr(engine, "create_engine")
assert hasattr(engine, "shutdown_engines")
assert hasattr(translation, "translate_body")
assert hasattr(translation, "resolve_review_model")
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
