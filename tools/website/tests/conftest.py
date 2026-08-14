"""Make ``tools/website`` importable so tests can import the loose scripts.

Run: ``cd tools && python -m pytest website/tests``
  or ``python -m pytest tools/website/tests`` from the repo root.
"""

from __future__ import annotations

import sys
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
WEBSITE_ROOT = _TESTS.parent
for _p in (str(_TESTS), str(WEBSITE_ROOT)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
