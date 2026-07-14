"""Hugo site deployment helper."""

from __future__ import annotations

import logging
import platform
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def run_hugo_update(hugo_site: Path) -> bool:
    """Run the Hugo site update script (cross-platform).

    Looks for ``update.sh`` (UNIX / Git Bash) or ``update.ps1`` (Windows).
    Returns True on success, False if no script found.

    ``hugo_site`` may be relative (e.g. ``tools/website`` from config); it is
    resolved against the gadget repo root so ``-File`` / bash script args stay
    correct regardless of the process cwd.
    """
    from common.paths import resolve_repo_path

    hugo_site = resolve_repo_path(hugo_site)
    sh_script = hugo_site / "update.sh"
    ps_script = hugo_site / "update.ps1"

    if platform.system() == "Windows":
        if ps_script.exists():
            logger.info("Running %s ...", ps_script)
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-File", str(ps_script)],
                cwd=str(hugo_site), check=True)
            logger.info("Hugo site deployed")
            return True
        elif sh_script.exists():
            bash_cmd = shutil.which("bash")
            if bash_cmd:
                logger.info("Running %s (via Git Bash) ...", sh_script)
                subprocess.run([bash_cmd, str(sh_script)],
                               cwd=str(hugo_site), check=True)
                logger.info("Hugo site deployed")
                return True
    else:
        if sh_script.exists():
            logger.info("Running %s ...", sh_script)
            subprocess.run(["bash", str(sh_script)],
                           cwd=str(hugo_site), check=True)
            logger.info("Hugo site deployed")
            return True

    logger.warning("No update script found (%s / %s), skipping deploy",
                   sh_script, ps_script)
    return False
