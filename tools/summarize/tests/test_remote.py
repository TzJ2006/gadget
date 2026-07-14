"""Tests for summarize rclone remote helpers — failure warnings."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from summarize import remote


def _fake_run(returncode: int, stderr: str = "", stdout: str = ""):
    def _run(*_args, **_kwargs):
        return SimpleNamespace(returncode=returncode, stderr=stderr, stdout=stdout)

    return _run


@pytest.fixture
def rclone_ready(monkeypatch, tmp_path):
    monkeypatch.setattr(
        remote,
        "_load_config",
        lambda: {"rclone_remote": "gdrive:gadget/summarize"},
    )
    monkeypatch.setattr(remote, "_find_rclone", lambda: "/usr/bin/rclone")
    return tmp_path


def test_upload_warns_and_skips_ok_on_rclone_failure(rclone_ready, monkeypatch, capsys):
    local = rclone_ready / "2026-07-14_dev.json"
    local.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        remote.subprocess,
        "run",
        _fake_run(
            1,
            stderr='Failed to load config file "/home/u/.config/rclone/rclone.conf": '
            "config file not found",
        ),
    )

    remote._rclone_upload(local, subdirectory="logs")
    out = capsys.readouterr().out

    assert "rclone upload" in out and "failed" in out
    assert "rclone is not currently working" in out
    assert "[ok] rclone" not in out


def test_download_logs_warns_on_missing_config_file(rclone_ready, monkeypatch, capsys):
    logs_dir = rclone_ready / "logs"
    monkeypatch.setattr(
        remote.subprocess,
        "run",
        _fake_run(
            1,
            stderr='Failed to load config file "/x/rclone.conf": config file not found',
        ),
    )

    matched = remote._rclone_download_logs(date(2026, 7, 14), logs_dir)
    out = capsys.readouterr().out

    assert matched == []
    assert "rclone is not currently working" in out
    assert "远端 logs/ 目录尚未创建" not in out


def test_download_logs_soft_skips_missing_remote_dir(rclone_ready, monkeypatch, capsys):
    logs_dir = rclone_ready / "logs"
    monkeypatch.setattr(
        remote.subprocess,
        "run",
        _fake_run(1, stderr="directory not found"),
    )

    matched = remote._rclone_download_logs(None, logs_dir)
    out = capsys.readouterr().out

    assert matched == []
    assert "远端 logs/ 目录尚未创建" in out
    assert "rclone is not currently working" not in out


def test_upload_warns_when_binary_missing(monkeypatch, capsys):
    monkeypatch.setattr(
        remote,
        "_load_config",
        lambda: {"rclone_remote": "gdrive:gadget/summarize"},
    )
    monkeypatch.setattr(remote, "_find_rclone", lambda: None)

    remote._rclone_upload(Path("/tmp/nope.json"), subdirectory="logs")
    out = capsys.readouterr().out

    assert "rclone is not currently working" in out
