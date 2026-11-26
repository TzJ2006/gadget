"""Fan out `summarize daily export` over SSH and pull the remote logs back.

Config (`summarize` section of repo-root config.json)::

    "ssh_hosts": [
        "user@box",                                   # repo defaults to ~/.gadget
        {"host": "gpu1", "repo": "/scratch/me/gadget", "python": "python3"}
    ]

``~/.gadget`` is the symlink `python scripts/onboard.py --only link` creates on
the remote — a fixed per-user handle for a checkout that can live anywhere.

Each host exports its own conversation logs locally, then this machine scp's
the JSON logs into its own logs dir — the normal `daily merge --sync-all`
stage then aggregates every device as usual.
"""

import shlex
import subprocess
from pathlib import Path

from common.paths import GADGET_ROOT

from .config import _load_config
from .daily_helpers import _DEFAULT_LOGS_DIR

_SSH_FLAGS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=10"]

# The remote's logs live at the same repo-relative path this machine exports to.
# Derived rather than spelled out: a literal "outputs/logs" drifted out of sync
# with daily_helpers once already, and the scp then matched nothing while the
# test asserting the wrong path stayed green.
try:
    _REMOTE_LOGS_REL = _DEFAULT_LOGS_DIR.relative_to(GADGET_ROOT).as_posix()
except ValueError:  # logs dir moved outside the repo — fall back to the layout
    _REMOTE_LOGS_REL = "outputs/logs/summarize"


def _hosts() -> list[dict]:
    out = []
    for entry in _load_config().get("ssh_hosts") or []:
        if isinstance(entry, str):
            entry = {"host": entry}
        host = entry.get("host")
        if not host:
            print(f"[warn] ssh_hosts entry without 'host', skipped: {entry}")
            continue
        out.append({
            "host": host,
            "repo": entry.get("repo", "~/.gadget"),
            "python": entry.get("python", "python3"),
        })
    return out


def _run(cmd: list[str], timeout: int) -> bool:
    try:
        r = subprocess.run(cmd, timeout=timeout)
        return r.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"[warn] timed out: {' '.join(cmd)}")
    except OSError as e:
        print(f"[warn] {e}: {' '.join(cmd)}")
    return False


def pull_remote_logs(local_logs_dir: Path, *, extra_args: list[str] | None = None) -> None:
    """Run the daily export on every configured SSH host and copy its logs here."""
    hosts = _hosts()
    if not hosts:
        return
    local_logs_dir.mkdir(parents=True, exist_ok=True)

    for h in hosts:
        print(f"\n[ssh] {h['host']}: {h['python']} -m summarize daily export")
        remote_cmd = (
            f"cd {shlex.quote(h['repo'])} && "
            + " ".join(shlex.quote(a) for a in
                       [h["python"], "-m", "summarize", "daily", "export", *(extra_args or [])])
        )
        # ponytail: export failure is non-fatal — still pull whatever logs exist.
        if not _run(["ssh", *_SSH_FLAGS, h["host"], remote_cmd], timeout=3600):
            print(f"[warn] remote export failed on {h['host']}, pulling existing logs anyway")

        src = f"{h['host']}:{h['repo'].rstrip('/')}/{_REMOTE_LOGS_REL}/*.json"
        if _run(["scp", "-q", *_SSH_FLAGS, src, str(local_logs_dir)], timeout=900):
            print(f"[ok] logs pulled from {h['host']}")
        else:
            print(f"[warn] no logs pulled from {h['host']}")
