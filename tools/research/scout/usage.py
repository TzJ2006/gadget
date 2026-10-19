"""Usage boundary for research.scout.

Does not search, call a model, or read a project. The business CLI remains
``python -m research.scout``.
"""

from __future__ import annotations

import sys

COMMANDS = ("list", "search", "ask", "report", "profile", "citations")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        print("用法: python -m research.scout.usage", file=sys.stderr)
        return 2
    names = ",".join(COMMANDS)
    print(f"用法: python -m research.scout {{{names}}}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
