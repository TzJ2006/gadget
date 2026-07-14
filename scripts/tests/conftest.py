"""Make ``scripts/`` importable so tests can ``import onboard``."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
