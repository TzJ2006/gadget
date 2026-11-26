from pathlib import Path
from unittest.mock import patch

from common.paths import GADGET_ROOT
from summarize import ssh_pull
from summarize.daily_helpers import _DEFAULT_LOGS_DIR

# Spelled out, not derived: this is the specification of where a remote export
# lands. Deriving it the way ssh_pull does would make the test agree with the
# code even when both are wrong — which is exactly what happened before.
REMOTE_LOGS_REL = "outputs/logs/summarize"


def test_remote_glob_matches_where_export_actually_writes():
    """The scp source must be the directory `daily export` writes into.

    These drifted apart once: ssh_pull globbed outputs/logs while the exporter
    wrote outputs/logs/summarize, so the copy matched nothing and only printed
    a warning. The test of the day asserted the wrong path, so it stayed green.
    """
    assert _DEFAULT_LOGS_DIR.relative_to(GADGET_ROOT).as_posix() == REMOTE_LOGS_REL
    assert ssh_pull._REMOTE_LOGS_REL == REMOTE_LOGS_REL


def test_pull_runs_export_then_scp(tmp_path):
    cfg = {"ssh_hosts": ["me@box", {"host": "gpu1", "repo": "/srv/gadget", "python": "py"}]}
    calls = []
    with patch.object(ssh_pull, "_load_config", return_value=cfg), \
         patch.object(ssh_pull, "_run", side_effect=lambda c, timeout: calls.append(c) or True):
        ssh_pull.pull_remote_logs(tmp_path)

    assert calls[0][:2] == ["ssh", "-o"] and calls[0][-2] == "me@box"
    assert "-m summarize daily export" in calls[0][-1]
    assert calls[1][0] == "scp"
    assert calls[1][-2] == f"me@box:~/.gadget/{REMOTE_LOGS_REL}/*.json"
    assert calls[2][-1].startswith("cd /srv/gadget && py ")
    assert calls[3][-2] == f"gpu1:/srv/gadget/{REMOTE_LOGS_REL}/*.json"


def test_no_hosts_is_noop(tmp_path):
    with patch.object(ssh_pull, "_load_config", return_value={}), \
         patch.object(ssh_pull, "_run", side_effect=AssertionError("should not run")):
        ssh_pull.pull_remote_logs(tmp_path / "nope")
    assert not (tmp_path / "nope").exists()
