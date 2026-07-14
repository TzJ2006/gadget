"""Tests for common.config — unified repo-root config.json."""

import json

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
