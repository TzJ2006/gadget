"""Tests for summarize auto onboarding checks."""

import io
import json
import os

import pytest

from summarize import auto, onboarding


def _by_key(results):
    return {result.key: result for result in results}


def test_auto_requirements_block_without_rclone_remote(monkeypatch, tmp_path):
    monkeypatch.setattr(onboarding, "_CONFIG_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(onboarding, "_load_config", lambda: {})
    monkeypatch.setattr(onboarding, "_ccusage_version", lambda: None)
    monkeypatch.setattr(
        onboarding.shutil,
        "which",
        lambda name: "/usr/bin/claude" if name == "claude" else None,
    )

    results = onboarding.check_auto_requirements(api="claude_cli")
    by_key = _by_key(results)

    assert by_key["rclone-remote"].status == "fail"
    assert by_key["llm-claude-cli"].status == "ok"
    assert onboarding.has_blocking_failures(results)


def test_auto_requirements_pass_with_remote_rclone_and_claude(monkeypatch, tmp_path):
    monkeypatch.setattr(onboarding, "_CONFIG_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(
        onboarding,
        "_load_config",
        lambda: {"rclone_remote": "gdrive:gadget/summarize"},
    )
    monkeypatch.setattr(onboarding, "_find_rclone", lambda: "/usr/bin/rclone")
    monkeypatch.setattr(onboarding, "_ccusage_version", lambda: (20, 0, 1))
    monkeypatch.setattr(
        onboarding.shutil,
        "which",
        lambda name: "/usr/bin/claude" if name == "claude" else None,
    )

    results = onboarding.check_auto_requirements(api="claude_cli")
    by_key = _by_key(results)

    assert by_key["rclone-remote"].status == "ok"
    assert by_key["rclone-binary"].status == "ok"
    assert by_key["llm-claude-cli"].status == "ok"
    assert not onboarding.has_blocking_failures(results)


def test_openai_backend_requires_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        onboarding.importlib.util,
        "find_spec",
        lambda name: object() if name == "openai" else None,
    )

    by_key = _by_key(onboarding._check_backend("openai"))

    assert by_key["llm-openai-package"].status == "ok"
    assert by_key["llm-openai-key"].status == "fail"


def test_hugo_deploy_check_passes_for_site_with_hugo_and_bash(monkeypatch, tmp_path):
    site = tmp_path / "website"
    site.mkdir()
    (site / "update.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")

    monkeypatch.setattr(onboarding.platform, "system", lambda: "Linux")
    monkeypatch.setattr(
        onboarding.shutil,
        "which",
        lambda name: {"hugo": "/usr/bin/hugo", "bash": "/bin/bash"}.get(name),
    )

    results = onboarding._check_hugo_deploy(site)

    assert not onboarding.has_blocking_failures(results)
    assert _by_key(results)["hugo-binary"].status == "ok"


def test_init_config_rechecks_freshly_written_config(monkeypatch, tmp_path):
    """--init-config must validate the config it just wrote."""
    from common import config as gadget_config
    from summarize import config as config_mod

    repo_cfg = tmp_path / "config.json"
    monkeypatch.setenv("GADGET_CONFIG", str(repo_cfg))
    gadget_config.clear_cache()
    monkeypatch.setattr(onboarding, "_CONFIG_PATH", repo_cfg)

    def fake_init():
        repo_cfg.write_text(
            json.dumps({"summarize": {"rclone_remote": "gdrive:gadget/summarize"}}),
            encoding="utf-8",
        )
        gadget_config.clear_cache()

    monkeypatch.setattr("summarize.daily._config_init", fake_init)
    monkeypatch.setattr(onboarding, "_find_rclone", lambda: "/usr/bin/rclone")
    monkeypatch.setattr(onboarding, "_ccusage_version", lambda: (20, 0, 1))
    monkeypatch.setattr(
        onboarding.shutil,
        "which",
        lambda name: "/usr/bin/claude" if name == "claude" else None,
    )

    args = type("Args", (), {
        "init_config": True,
        "api": "claude_cli",
        "deploy": False,
        "hugo_site": None,
        "json": False,
    })()

    onboarding.cmd_onboard(args)  # must not sys.exit(1) after a successful init


def test_ensure_auto_ready_prints_blocking_guidance(monkeypatch):
    failure = onboarding.RequirementResult(
        "missing",
        "Missing thing",
        "fail",
        True,
        "not ready",
        "fix it",
    )
    monkeypatch.setattr(
        onboarding,
        "check_auto_requirements",
        lambda **_: [failure],
    )

    stream = io.StringIO()

    assert not onboarding.ensure_auto_ready(stream=stream)
    assert "Blocking requirements are missing" in stream.getvalue()


def test_cmd_auto_exits_before_work_when_readiness_fails(monkeypatch):
    args = type("Args", (), {
        "date": None,
        "api": "claude_cli",
        "deploy": False,
        "force": False,
        "hugo_site": None,
        "skip_onboard_check": False,
    })()
    monkeypatch.setattr(auto, "ensure_auto_ready", lambda **_: False)
    monkeypatch.setattr(auto, "_run", lambda _: pytest.fail("auto should not run"))

    with pytest.raises(SystemExit) as exc:
        auto.cmd_auto(args)

    assert exc.value.code == 2


def test_cmd_auto_skip_check_passes_hugo_site_to_deploy_commands(monkeypatch, capsys):
    calls = []
    args = type("Args", (), {
        "date": "2026-01-02",
        "api": "anthropic",
        "deploy": True,
        "force": True,
        "hugo_site": "/tmp/site",
        "skip_onboard_check": True,
    })()
    monkeypatch.setattr(
        auto,
        "ensure_auto_ready",
        lambda **_: pytest.fail("readiness check should be skipped"),
    )
    monkeypatch.setattr(
        auto,
        "_run",
        lambda cmd, **kwargs: calls.append((cmd, kwargs)) or True,
    )
    monkeypatch.setattr(auto, "_find_missing_weeks", lambda _: ["2026-W01"])
    monkeypatch.setattr(auto, "_find_missing_months", lambda _: ["2026-01"])
    monkeypatch.setattr(auto, "_unload_ollama", lambda: None)

    auto.cmd_auto(args)

    deploy_commands = [(cmd, kwargs) for cmd, kwargs in calls if "--deploy" in cmd]
    assert len(deploy_commands) == 3  # merge + weekly + monthly
    assert all("--hugo-site" in cmd for cmd, _ in deploy_commands)
    assert all("/tmp/site" in cmd for cmd, _ in deploy_commands)
    assert all(kwargs == {"defer_hugo_update": True}
               for _, kwargs in deploy_commands)

    final_cmd, final_kwargs = calls[-1]
    assert final_cmd[2:5] == ["summarize", "daily", "deploy"]
    assert final_kwargs == {}

    output = capsys.readouterr().out
    assert "[auto] Date aggregation target: 2026-01-02" in output
    assert "[auto] Week aggregation target: 2026-W01" in output
    assert "[auto] Month aggregation target: 2026-01" in output


def test_auto_regenerates_stale_week_and_month(tmp_path, capsys):
    daily = tmp_path / "2026-01-01.json"
    weekly = tmp_path / "2026-W01-weekly.json"
    monthly = tmp_path / "2026-01-monthly.json"
    for report in (daily, weekly, monthly):
        report.write_text("{}", encoding="utf-8")

    os.utime(weekly, (100, 100))
    os.utime(monthly, (100, 100))
    os.utime(daily, (200, 200))

    assert auto._find_missing_weeks(tmp_path) == ["2026-W01"]
    assert auto._find_missing_months(tmp_path) == ["2026-01"]

    output = capsys.readouterr().out
    assert "共发现 1 个有日报数据的 weeks: 2026-W01" in output
    assert "需重新生成 2026-W01（日报比周报新）" in output
    assert "weeks 扫描完成: 跳过 0 个，需生成 1 个: 2026-W01" in output
    assert "共发现 1 个有日报数据的 months: 2026-01" in output
    assert "需重新生成 2026-01（日报比月报新）" in output
    assert "months 扫描完成: 跳过 0 个，需生成 1 个: 2026-01" in output


def test_auto_logs_missing_and_up_to_date_aggregates(tmp_path, capsys):
    daily = tmp_path / "2026-01-01.json"
    daily.write_text("{}", encoding="utf-8")

    assert auto._find_missing_weeks(tmp_path) == ["2026-W01"]
    assert auto._find_missing_months(tmp_path) == ["2026-01"]
    missing_output = capsys.readouterr().out
    assert "需生成 2026-W01（周报不存在）" in missing_output
    assert "需生成 2026-01（月报不存在）" in missing_output

    weekly = tmp_path / "2026-W01-weekly.json"
    monthly = tmp_path / "2026-01-monthly.json"
    weekly.write_text("{}", encoding="utf-8")
    monthly.write_text("{}", encoding="utf-8")
    os.utime(daily, (100, 100))
    os.utime(weekly, (200, 200))
    os.utime(monthly, (200, 200))

    assert auto._find_missing_weeks(tmp_path) == []
    assert auto._find_missing_months(tmp_path) == []
    up_to_date_output = capsys.readouterr().out
    assert "跳过 2026-W01（周报已是最新）" in up_to_date_output
    assert "跳过 2026-01（月报已是最新）" in up_to_date_output


def test_cmd_auto_logs_when_no_aggregate_command_runs(monkeypatch, capsys):
    calls = []
    args = type("Args", (), {
        "date": "2026-01-02",
        "api": "ollama",
        "deploy": False,
        "force": False,
        "hugo_site": None,
        "skip_onboard_check": True,
    })()
    monkeypatch.setattr(
        auto,
        "_run",
        lambda cmd, **kwargs: calls.append((cmd, kwargs)) or True,
    )
    monkeypatch.setattr(auto, "_find_missing_weeks", lambda _: [])
    monkeypatch.setattr(auto, "_find_missing_months", lambda _: [])
    monkeypatch.setattr(auto, "_unload_ollama", lambda: None)

    auto.cmd_auto(args)

    output = capsys.readouterr().out
    assert "[auto] Weekly command: none (没有需要生成的周报)" in output
    assert "[auto] Monthly command: none (没有需要生成的月报)" in output
    assert not any("weekly" in cmd for cmd, _ in calls)
    assert not any("monthly" in cmd for cmd, _ in calls)
