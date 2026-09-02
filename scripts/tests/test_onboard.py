"""Mocked tests for scripts/onboard.py — no real network/npm/ssh.

Run: python -m pytest scripts/tests/test_onboard.py -q
"""

import json
import subprocess

import pytest

import onboard


# --- step selection ---------------------------------------------------------


def test_active_steps_enabled_only_skip():
    sheet = {
        "ssh": {"enabled": True},
        "claude": {"enabled": False},
        "install": {"enabled": True},
    }
    assert onboard._active_steps(sheet, None, None) == ["ssh", "install"]
    # --only overrides enabled, preserving registry order
    assert onboard._active_steps(sheet, ["gadgets", "claude"], None) == ["claude", "gadgets"]
    # --skip subtracts
    assert onboard._active_steps(sheet, None, ["install"]) == ["ssh"]


def test_load_sheet(tmp_path):
    p = tmp_path / "s.yaml"
    p.write_text("ssh:\n  enabled: true\nclaude:\n  enabled: false\n", encoding="utf-8")
    data = onboard._load_sheet(p)
    assert data["ssh"]["enabled"] is True
    assert data["claude"]["enabled"] is False


def test_run_steps_catches_exception(monkeypatch):
    def boom(cfg, ctx):
        raise RuntimeError("kaboom")

    def good(cfg, ctx):
        return onboard.StepResult("install", "ok", "done")

    monkeypatch.setattr(onboard, "STEPS", [("ssh", boom), ("install", good)])
    ctx = onboard.Ctx(dry_run=False, assume_yes=True, sheet={"ssh": {}, "install": {}})
    results = {r.name: r for r in onboard.run_steps(["ssh", "install"], ctx)}
    assert results["ssh"].status == "failed"          # raising step caught
    assert results["install"].status == "ok"          # loop continued


# --- claude auth ------------------------------------------------------------


def test_build_env_block_drops_empty():
    env = onboard._build_env_block(
        "bedrock",
        {"bedrock": {"AWS_REGION": "us-east-1", "AWS_PROFILE": "", "AWS_ACCESS_KEY_ID": ""}},
    )
    assert env["CLAUDE_CODE_USE_BEDROCK"] == "1"
    assert env["AWS_REGION"] == "us-east-1"
    assert "AWS_PROFILE" not in env and "AWS_ACCESS_KEY_ID" not in env


def test_claude_auth_mode_exclusion(tmp_path, monkeypatch):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "env": {"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_REGION": "us-west-2", "KEEP": "me"},
        "hooks": {"x": 1},
    }), encoding="utf-8")
    monkeypatch.setattr(onboard, "CLAUDE_USER_SETTINGS", settings)

    ctx = onboard.Ctx(dry_run=False, assume_yes=True, sheet={})
    onboard._write_claude_auth("api", {"api": {"ANTHROPIC_API_KEY": "sk-ant-xxx"}}, ctx)

    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["env"]["ANTHROPIC_API_KEY"] == "sk-ant-xxx"
    assert "CLAUDE_CODE_USE_BEDROCK" not in data["env"]   # prior mode stripped
    assert "AWS_REGION" not in data["env"]                # shared var stripped too
    assert data["env"]["KEEP"] == "me"                    # unrelated env preserved
    assert data["hooks"] == {"x": 1}                      # unrelated top-level preserved


# --- ssh config -------------------------------------------------------------


def test_ssh_config_idempotent_and_preserves(tmp_path, monkeypatch):
    cfgfile = tmp_path / "config"
    cfgfile.write_text("Host other\n    HostName other.example\n", encoding="utf-8")
    monkeypatch.setattr(onboard, "SSH_CONFIG", cfgfile)
    monkeypatch.setattr(onboard, "SSH_DIR", tmp_path)

    host = {"alias": "gpu1", "hostname": "gpu1.ex", "user": "me", "port": 22,
            "identity_file": "~/.ssh/id_ed25519"}
    changed1 = onboard._upsert_ssh_config(host, dry_run=False)
    changed2 = onboard._upsert_ssh_config(host, dry_run=False)

    text = cfgfile.read_text(encoding="utf-8")
    assert changed1 is True and changed2 is False        # idempotent on re-run
    assert text.count("Host gpu1") == 1                  # exactly one managed block
    assert "Host other" in text                          # unrelated block untouched


# --- gadgets: research section merge ---------------------------------------


def test_research_config_merges_into_root(monkeypatch):
    ctx = onboard.Ctx(dry_run=False, assume_yes=True, sheet={})
    root = {"research": {"model": "sonnet", "max_students": 10}}
    onboard._write_research_config({"model": "opus", "output_dir": ""}, root, ctx)

    assert root["research"]["model"] == "opus"            # sheet value wins
    assert root["research"]["max_students"] == 10         # preserved from current
    assert "output_dir" not in root["research"]           # empty value dropped


# --- claude plugin list except-path -----------------------------------------


def _plugin_ctx():
    return onboard.Ctx(dry_run=False, assume_yes=True, sheet={})


def test_install_claude_plugin_list_oserror_warns_and_continues(monkeypatch, capsys):
    installs = []
    monkeypatch.setattr(onboard, "_which", lambda name: "/bin/claude")

    def fake_run(cmd, **kwargs):
        raise OSError("claude vanished")

    monkeypatch.setattr(onboard.subprocess, "run", fake_run)
    monkeypatch.setattr(onboard, "_run", lambda cmd, **kw: installs.append(cmd) or True)

    onboard._install_claude_plugin("ponytail@claude-plugins-official", _plugin_ctx())
    out = capsys.readouterr().out
    assert "[warn]" in out and "plugin list failed" in out
    assert "continuing with install" in out
    assert installs == [["/bin/claude", "plugin", "install", "ponytail@claude-plugins-official"]]


def test_install_claude_plugin_list_timeout_warns_and_continues(monkeypatch, capsys):
    installs = []
    monkeypatch.setattr(onboard, "_which", lambda name: "/bin/claude")

    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 60)

    monkeypatch.setattr(onboard.subprocess, "run", fake_run)
    monkeypatch.setattr(onboard, "_run", lambda cmd, **kw: installs.append(cmd) or True)

    onboard._install_claude_plugin("foo@bar", _plugin_ctx())
    out = capsys.readouterr().out
    assert "[warn]" in out and "plugin list failed" in out
    assert installs


def test_install_claude_plugin_list_nonzero_warns_and_continues(monkeypatch, capsys):
    installs = []
    monkeypatch.setattr(onboard, "_which", lambda name: "/bin/claude")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="plugin list exploded")

    monkeypatch.setattr(onboard.subprocess, "run", fake_run)
    monkeypatch.setattr(onboard, "_run", lambda cmd, **kw: installs.append(cmd) or True)

    onboard._install_claude_plugin("foo@bar", _plugin_ctx())
    out = capsys.readouterr().out
    assert "[warn]" in out and "plugin list failed" in out
    assert "plugin list exploded" in out
    assert installs


def test_install_claude_plugin_skips_when_already_listed(monkeypatch, capsys):
    installs = []
    monkeypatch.setattr(onboard, "_which", lambda name: "/bin/claude")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="foo@bar\nother@x\n", stderr="")

    monkeypatch.setattr(onboard.subprocess, "run", fake_run)
    monkeypatch.setattr(onboard, "_run", lambda cmd, **kw: installs.append(cmd) or True)

    onboard._install_claude_plugin("foo@bar", _plugin_ctx())
    out = capsys.readouterr().out
    assert "[skip] plugin already installed: foo@bar" in out
    assert installs == []


# --- step: link -------------------------------------------------------------


def _symlinks_work(tmp_path) -> bool:
    try:
        (tmp_path / "probe").symlink_to(tmp_path, target_is_directory=True)
    except OSError:  # Windows without Developer Mode
        return False
    (tmp_path / "probe").unlink()
    return True


def test_step_link_creates_and_repoints(tmp_path, monkeypatch):
    if not _symlinks_work(tmp_path):
        pytest.skip("symlinks unavailable on this host")
    monkeypatch.setattr(onboard, "IS_WINDOWS", False)
    monkeypatch.setattr(onboard, "GADGET_ROOT", tmp_path / "repo")
    (tmp_path / "repo").mkdir()
    (tmp_path / "old").mkdir()
    link = tmp_path / "home" / ".gadget"
    link.parent.mkdir()
    ctx = onboard.Ctx(dry_run=False, assume_yes=True)

    r = onboard.step_link({"path": str(link), "private": False}, ctx)
    assert r.status == "ok" and link.resolve() == tmp_path / "repo"

    onboard.step_link({"path": str(link), "private": False}, ctx)  # idempotent
    assert link.resolve() == tmp_path / "repo"

    link.unlink()
    link.symlink_to(tmp_path / "old", target_is_directory=True)
    assert onboard.step_link({"path": str(link), "private": False}, ctx).status == "ok"
    assert link.resolve() == tmp_path / "repo"


def test_step_link_refuses_real_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(onboard, "GADGET_ROOT", tmp_path / "repo")
    real = tmp_path / ".gadget"
    real.mkdir()
    r = onboard.step_link({"path": str(real)}, onboard.Ctx(dry_run=False, assume_yes=True))
    assert r.status == "failed"
