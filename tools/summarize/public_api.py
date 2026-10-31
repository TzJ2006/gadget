"""Public summarize entry.

Call ``python -m summarize.public_api`` in the tool interpreter. Callers outside
this package do not import ``_call_*``. An empty request prints usage and does
not load a model.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path
from contextlib import redirect_stdout
import hashlib


def implementation_id() -> str:
    """Content identity of the engine and transport, not the caller's version."""
    root = Path(__file__).resolve().parent
    from common import llm, ollama_chat, json_utils
    paths = [root / name for name in ("public_api.py", "summarizer.py", "chunks.py", "period_report.py", "periods.py",
                                     "weekly_summary.py", "monthly_summary.py")]
    paths += [Path(module.__file__) for module in (llm, ollama_chat, json_utils)]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.read_bytes())
    return digest.hexdigest()


def summarize_daily(api: str, conversations: list, day: str, **options) -> dict:
    from summarize.summarizer import _call_summarize

    return require_report(_call_summarize(api, conversations, date.fromisoformat(day), **options))


def require_report(result):
    if not isinstance(result, dict) or result.get("parse_error") or not str(result.get("summary") or "").strip():
        raise ValueError("Model did not return a usable report")
    return result


def report_directory(override=None):
    from .config import _resolve_output_dir
    from common.paths import REPORTS_DIR
    return _resolve_output_dir(override, "SUMMARIZE_REPORTS_DIR", "reports_dir", REPORTS_DIR / "summarize")


def dispatch(payload: dict) -> dict:
    """Explicit-input operations only: never discover/sync/publish as a side effect."""
    from common.llm import total_budget
    op = payload.get("op")
    if op == "version":
        return {"implementation": implementation_id()}
    if payload.get("implementation") not in (None, implementation_id()):
        raise ValueError("Interpreter has a different summarize version")
    if op == "parse":
        from summarize.records import load_records
        start = date.fromisoformat(payload["date"]) if payload.get("date") else None
        end = date.fromisoformat(payload["until_date"]) if payload.get("until_date") else None
        texts, summaries = load_records(payload["kind"], Path(payload["path"]), on_date=start, until_date=end)
        return {"texts": texts, "summaries": summaries}
    if payload.get("save_dir"):
        return save_report(payload)
    timeout = float(payload.get("timeout", 600))
    with total_budget(timeout, model=payload.get("model")):
        api = str(payload.get("api") or "ollama")
        if op == "daily":
            conversations = payload.get("conversations")
            if not isinstance(conversations, list) or not conversations:
                raise ValueError("Expected nonempty conversations")
            for conv in conversations:
                if not isinstance(conv, dict) or not isinstance(conv.get("messages"), list):
                    raise ValueError("Invalid conversation")
                for message in conv["messages"]:
                    if not isinstance(message, dict) or not isinstance(message.get("content"), str):
                        raise ValueError("Invalid message")
            return summarize_daily(api, conversations, str(payload.get("day") or ""),
                timeout=timeout, max_chars=int(payload.get("chunk_chars", 150000)),
                overlap=int(payload.get("overlap_chars", 0)),
                cache_context=str(payload.get("cache_context", "")),
                chunk_cache_dir=Path(payload["cache_dir"]) if payload.get("cache_dir") else None)
        if op == "period":
            return summarize_period(api, str(payload.get("kind") or ""),
                                    str(payload.get("label") or ""), list(payload.get("daily_reports") or []))
        raise ValueError("Unknown operation")


# Compatibility export; period validation has one owner.
from summarize.periods import report_name


def save_report(payload):
    """Persist the same report format used by existing daily/period CLIs."""
    from common.io import atomic_write
    request = dict(payload)
    directory = Path(request.pop("save_dir"))
    force = bool(request.pop("force", False))
    if force:
        request.pop("cache_dir", None)
    kind = "day" if request["op"] == "daily" else request["kind"]
    label = request.get("day") if kind == "day" else request["label"]
    destination = directory / report_name(kind, label)
    identity = {k: v for k, v in request.items() if k not in {"timeout", "cache_dir"}}
    identity["implementation"] = implementation_id()
    digest = hashlib.sha256(json.dumps(identity, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if destination.is_file() and not force:
        saved = json.loads(destination.read_text(encoding="utf-8"))
        # Preserve legacy CLI reports; never regenerate them just because they
        # predate this entrypoint. Changed reports created here are recomputed.
        if saved.get("_generation_hash") in (None, digest):
            return saved
    result = dispatch(request)
    result["_generation_hash"] = digest
    if kind == "day":
        result["date"] = label
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write(destination, json.dumps(result, ensure_ascii=False, indent=2))
    return result


def summarize_period(api: str, kind: str, label: str, daily_reports: list) -> dict:
    if kind == "week":
        from summarize.weekly_summary import _call_weekly_summarize_chunked

        return require_report(_call_weekly_summarize_chunked(api, daily_reports, label, chunk_cache_dir=None))
    if kind == "month":
        from summarize.monthly_summary import _call_monthly_summarize_chunked

        return require_report(_call_monthly_summarize_chunked(api, daily_reports, label, chunk_cache_dir=None))
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
    try:
        with redirect_stdout(sys.stderr):
            result = dispatch(payload)
    except Exception as exc:
        # Provider errors can echo private prompts or credentials.
        print(f"summarize failed: {exc.__class__.__name__}", file=sys.stderr)
        return 1
    sys.stdout.write(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
