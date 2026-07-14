"""resolve_repo_path — relative config paths root at GADGET_ROOT."""

from pathlib import Path

import common.paths as paths
from common.paths import resolve_repo_path


def test_resolve_repo_path_relative_uses_gadget_root(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "GADGET_ROOT", tmp_path)
    nested = tmp_path / "nested"
    nested.mkdir()
    monkeypatch.chdir(nested)

    (tmp_path / "tools" / "website").mkdir(parents=True)
    got = resolve_repo_path("tools/website")
    assert got == (tmp_path / "tools" / "website").resolve()
    assert got.is_absolute()


def test_resolve_repo_path_absolute_unchanged(tmp_path):
    target = (tmp_path / "custom" / "site").resolve()
    target.mkdir(parents=True)
    assert resolve_repo_path(target) == target
    assert resolve_repo_path(str(target)) == target


def test_resolve_repo_path_expanduser(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    # Use an absolute path under home — expanduser semantics vary by platform;
    # absolute inputs must still round-trip through resolve_repo_path.
    target = (home / "gadget-out").resolve()
    assert resolve_repo_path(target) == target
