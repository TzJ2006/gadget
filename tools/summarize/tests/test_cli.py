"""CLI / daily re-export contracts after the daily.py split."""

import argparse

from common.llm import DEFAULT_BACKEND, LLM_BACKENDS
from summarize.cli import add_api_flag, add_export_flags, add_hugo_site_flag, build_parser
from summarize.config import resolve_hugo_site
from summarize.daily import (
    cmd_config,
    cmd_deploy,
    cmd_export,
    cmd_export_past,
    cmd_merge,
    _config_init,
)


def test_daily_reexports_commands():
    assert callable(cmd_export)
    assert callable(cmd_export_past)
    assert callable(cmd_merge)
    assert callable(cmd_deploy)
    assert callable(cmd_config)
    assert callable(_config_init)


def test_cmd_legacy_removed():
    import summarize.daily as daily

    assert not hasattr(daily, "cmd_legacy")


def test_add_api_flag_uses_llm_backends():
    parser = argparse.ArgumentParser()
    add_api_flag(parser)
    action = parser._option_string_actions["--api"]
    assert list(action.choices) == list(LLM_BACKENDS)
    assert parser.parse_args([]).api == DEFAULT_BACKEND


def test_build_parser_api_and_hugo_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("GADGET_CONFIG", str(tmp_path / "missing.json"))
    from common import config as gadget_config
    gadget_config.clear_cache()

    parser = build_parser()
    merge = parser.parse_args(["merge"])
    export = parser.parse_args(["export", "--date", "2026-01-01"])
    deploy = parser.parse_args(["deploy"])

    assert merge.api == DEFAULT_BACKEND
    assert export.api == DEFAULT_BACKEND
    assert merge.hugo_site == str(resolve_hugo_site())
    assert deploy.hugo_site == str(resolve_hugo_site())

    api_action = None
    for action in parser._actions:
        if "--api" in getattr(action, "option_strings", ()):
            api_action = action
            break
    assert api_action is not None
    assert list(api_action.choices) == list(LLM_BACKENDS)


def test_export_flag_helper_attaches_shared_flags():
    parser = argparse.ArgumentParser()
    add_export_flags(parser)
    ns = parser.parse_args([])
    assert ns.date is None
    assert ns.chatgpt is None
    assert ns.generic == []
    assert ns.summarize is False
    assert ns.api == DEFAULT_BACKEND
    assert ns.export_past is False


def test_hugo_site_flag_uses_resolve_hugo_site():
    parser = argparse.ArgumentParser()
    add_hugo_site_flag(parser)
    assert parser.parse_args([]).hugo_site == str(resolve_hugo_site())
