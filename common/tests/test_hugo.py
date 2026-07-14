"""run_hugo_update path resolution — relative hugo_site must become absolute."""

from pathlib import Path
from unittest.mock import patch

from common.hugo import run_hugo_update
import common.paths as paths


def test_run_hugo_update_resolves_relative_ps1_path(tmp_path, monkeypatch):
    """Relative hugo_site is rooted at GADGET_ROOT, not nested under cwd."""
    site = tmp_path / "tools" / "website"
    site.mkdir(parents=True)
    (site / "update.ps1").write_text("# stub\n", encoding="utf-8")

    monkeypatch.setattr(paths, "GADGET_ROOT", tmp_path)
    # cwd elsewhere — must still resolve via repo root
    monkeypatch.chdir(tmp_path / "tools")

    with patch("common.hugo.platform.system", return_value="Windows"), \
         patch("common.hugo.subprocess.run") as mock_run:
        assert run_hugo_update(Path("tools/website")) is True

    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    cmd = args[0]
    assert cmd[0] == "powershell"
    file_arg = cmd[cmd.index("-File") + 1]
    assert Path(file_arg).is_absolute()
    assert Path(file_arg) == (site / "update.ps1").resolve()
    assert Path(kwargs["cwd"]).is_absolute()
    assert Path(kwargs["cwd"]) == site.resolve()


def test_run_hugo_update_resolves_relative_sh_path(tmp_path, monkeypatch):
    site = tmp_path / "tools" / "website"
    site.mkdir(parents=True)
    (site / "update.sh").write_text("#!/bin/bash\n", encoding="utf-8")

    monkeypatch.setattr(paths, "GADGET_ROOT", tmp_path)
    monkeypatch.chdir(tmp_path / "tools")

    with patch("common.hugo.platform.system", return_value="Linux"), \
         patch("common.hugo.subprocess.run") as mock_run:
        assert run_hugo_update(Path("tools/website")) is True

    mock_run.assert_called_once()
    args, kwargs = mock_run.call_args
    cmd = args[0]
    assert cmd[0] == "bash"
    assert Path(cmd[1]).is_absolute()
    assert Path(cmd[1]) == (site / "update.sh").resolve()
    assert Path(kwargs["cwd"]) == site.resolve()


def test_run_hugo_update_missing_script_returns_false(tmp_path):
    site = tmp_path / "empty-site"
    site.mkdir()
    with patch("common.hugo.platform.system", return_value="Windows"):
        assert run_hugo_update(site) is False
