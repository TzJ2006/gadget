#!/usr/bin/env python3
"""
Submit a benchmark result row to a relay endpoint or GitHub repository_dispatch.

Typical use:
1) Run benchmark locally (writes benchmark_results.csv).
2) Submit latest row:
   python scripts/submit_result.py --input-csv benchmark_results.csv --relay-url https://example.com/submit

Direct GitHub dispatch mode (for trusted callers):
   python scripts/submit_result.py --github-owner ORG --github-repo REPO --github-token $TOKEN
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


INT_FIELDS = {"cpu_cores", "matrix_size", "iterations"}
FLOAT_FIELDS = {"gpu_memory_gb", "flops_gflops", "time_seconds"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def coerce_row_types(row: Dict[str, Any]) -> Dict[str, Any]:
    typed: Dict[str, Any] = {}
    for key, value in row.items():
        if key in INT_FIELDS:
            typed[key] = int(float(value))
        elif key in FLOAT_FIELDS:
            typed[key] = float(value)
        else:
            typed[key] = value
    return typed


def load_row_from_csv(csv_path: Path, row_index: int) -> Dict[str, Any]:
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"CSV has no data rows: {csv_path}")

    selected = rows[row_index]
    return coerce_row_types(selected)


def load_row_from_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"JSON file not found: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("submission"), dict):
        payload = payload["submission"]
    if not isinstance(payload, dict):
        raise ValueError("submission JSON must be an object or {'submission': {...}}")
    return payload


def post_json(url: str, payload: Dict[str, Any], headers: Dict[str, str], timeout: int) -> None:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url=url, data=body, method="POST")
    request.add_header("Content-Type", "application/json")
    for key, value in headers.items():
        request.add_header(key, value)

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status = response.getcode()
            raw = response.read().decode("utf-8", errors="replace")
            print(f"Request succeeded: HTTP {status}")
            if raw.strip():
                print(raw.strip())
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Request failed: {exc}") from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit benchmark result row")
    parser.add_argument("--input-csv", type=Path, default=Path("benchmark_results.csv"))
    parser.add_argument("--row-index", type=int, default=-1, help="Row index from CSV (default: last row)")
    parser.add_argument("--submission-json", type=Path, default=None, help="Optional JSON file to submit")

    parser.add_argument("--relay-url", type=str, default="", help="Relay endpoint URL")
    parser.add_argument("--github-owner", type=str, default="")
    parser.add_argument("--github-repo", type=str, default="")
    parser.add_argument("--github-token", type=str, default=os.getenv("GITHUB_TOKEN", ""))
    parser.add_argument("--event-type", type=str, default="benchmark_submission")

    parser.add_argument("--source-id", type=str, default="", help="Optional caller identifier")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.submission_json:
        submission = load_row_from_json(args.submission_json)
    else:
        submission = load_row_from_csv(args.input_csv, args.row_index)

    payload: Dict[str, Any] = {
        "submission": submission,
        "source": {
            "submitted_via": "scripts/submit_result.py",
            "source_id": args.source_id,
            "submitted_at_utc": utc_now_iso(),
        },
    }

    if args.dry_run:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    if args.relay_url:
        post_json(args.relay_url, payload, headers={}, timeout=args.timeout)
        return 0

    if not args.github_owner or not args.github_repo or not args.github_token:
        raise SystemExit(
            "Provide --relay-url OR all of --github-owner, --github-repo, and --github-token."
        )

    dispatch_url = (
        f"https://api.github.com/repos/{args.github_owner}/{args.github_repo}/dispatches"
    )
    dispatch_payload = {
        "event_type": args.event_type,
        "client_payload": payload,
    }
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {args.github_token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    post_json(dispatch_url, dispatch_payload, headers=headers, timeout=args.timeout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
