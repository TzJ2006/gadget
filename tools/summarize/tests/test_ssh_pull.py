from pathlib import Path
from unittest.mock import patch

from summarize import ssh_pull


def test_pull_runs_export_then_scp(tmp_path):
    cfg = {"ssh_hosts": ["me@box", {"host": "gpu1", "repo": "/srv/gadget", "python": "py"}]}
    calls = []
    with patch.object(ssh_pull, "_load_config", return_value=cfg), \
         patch.object(ssh_pull, "_run", side_effect=lambda c, timeout: calls.append(c) or True):
        ssh_pull.pull_remote_logs(tmp_path)

    assert calls[0][:2] == ["ssh", "-o"] and calls[0][-2] == "me@box"
    assert "-m summarize daily export" in calls[0][-1]
    assert calls[1][0] == "scp" and calls[1][-2].startswith("me@box:~/.gadget/outputs/logs/")
    assert calls[2][-1].startswith("cd /srv/gadget && py ")
    assert calls[3][-2] == "gpu1:/srv/gadget/outputs/logs/*.json"


def test_no_hosts_is_noop(tmp_path):
    with patch.object(ssh_pull, "_load_config", return_value={}), \
         patch.object(ssh_pull, "_run", side_effect=AssertionError("should not run")):
        ssh_pull.pull_remote_logs(tmp_path / "nope")
    assert not (tmp_path / "nope").exists()
