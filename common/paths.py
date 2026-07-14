"""Canonical output directory paths for all gadget tools."""
from pathlib import Path

GADGET_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = GADGET_ROOT / "tools"
OUTPUTS_DIR = GADGET_ROOT / "outputs"

REPORTS_DIR = OUTPUTS_DIR / "reports"
LOGS_DIR = OUTPUTS_DIR / "logs"
CACHE_DIR = OUTPUTS_DIR / "cache"
DATA_DIR = OUTPUTS_DIR / "data"
IMAGES_DIR = OUTPUTS_DIR / "images"


def resolve_repo_path(value: str | Path) -> Path:
    """Resolve a config/CLI filesystem path against the gadget repo root.

    Absolute paths and ``~`` expansions are kept. Relative paths are rooted at
    ``GADGET_ROOT`` (not the process cwd), so values like ``tools/website`` work
    regardless of where the command was launched.
    """
    p = Path(value).expanduser()
    if not p.is_absolute():
        p = GADGET_ROOT / p
    return p.resolve()
