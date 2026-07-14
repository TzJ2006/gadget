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
