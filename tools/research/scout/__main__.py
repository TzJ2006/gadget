"""Entry point for `python -m research.scout`."""

import sys as _sys
from pathlib import Path as _Path

# Under `python -m research.scout`, sys.path[0] is the repo root, so the
# top-level `scout` package (and `research.*` lazy imports inside it) are not
# importable. Put research/ (for `scout`) and the repo root (for `research`)
# on the path before importing the package's own modules.
_here = _Path(__file__).resolve()
for _p in (str(_here.parent.parent), str(_here.parent.parent.parent)):
    if _p not in _sys.path:
        _sys.path.insert(0, _p)

from scout.cli import main

if __name__ == "__main__":
    main()
