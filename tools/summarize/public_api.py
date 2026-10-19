"""Public summarize entry.

Call ``python -m summarize.public_api`` in the tool interpreter. Callers outside
this package do not import ``_call_*``. An empty request prints usage and does
not load a model.
"""

from __future__ import annotations

import json
import sys
from datetime import date


def summarize_daily(api: str, conversations: list, day: str) -> dict:
    from summarize.summarizer import _call_summarize

    return _call_summarize(api, conversations, date.fromisoformat(day), chunk_cache_dir=None)


def summarize_period(api: str, kind: str, label: str, daily_reports: list) -> dict:
    if kind == "week":
        from summarize.weekly_summary import _call_weekly_summarize_chunked

        return _call_weekly_summarize_chunked(api, daily_reports, label, chunk_cache_dir=None)
    if kind == "month":
        from summarize.monthly_summary import _call_monthly_summarize_chunked

        return _call_monthly_summarize_chunked(api, daily_reports, label, chunk_cache_dir=None)
    raise ValueError(f"未知周期: {kind}")


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args:
        print("用法: python -m summarize.public_api < json", file=sys.stderr)
        return 2
    raw = sys.stdin.read()
    if not raw.strip():
        print("用法: python -m summarize.public_api < json", file=sys.stderr)
        return 2
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        print("用法: 请求必须是 JSON 对象", file=sys.stderr)
        return 2
    if not isinstance(payload, dict):
        print("用法: 请求必须是 JSON 对象", file=sys.stderr)
        return 2
    op = str(payload.get("op") or "")
    api = str(payload.get("api") or "ollama")
    try:
        if op == "daily":
            result = summarize_daily(api, list(payload.get("conversations") or []), str(payload.get("day") or ""))
        elif op == "period":
            result = summarize_period(
                api,
                str(payload.get("kind") or ""),
                str(payload.get("label") or ""),
                list(payload.get("daily_reports") or []),
            )
        else:
            print("用法: op 只能是 daily 或 period", file=sys.stderr)
            return 2
    except Exception as exc:
        print(f"{exc.__class__.__name__}: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
