#!/usr/bin/env python3
"""
Ingest queued benchmark submissions into benchmark_results.csv.

Pipeline:
1. Read raw NDJSON records from a pending queue.
2. Validate schema and value ranges.
3. Sanitize potentially identifying text fields.
4. Deduplicate by fingerprint.
5. Append accepted rows to benchmark_results.csv.
6. Log rejects and write an ingest summary.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


CSV_COLUMNS: List[str] = [
    "timestamp",
    "cpu_model",
    "cpu_cores",
    "cpu_frequency",
    "gpu_vendor",
    "gpu_model",
    "gpu_memory_gb",
    "gpu_compute_capability",
    "benchmark_name",
    "benchmark_type",
    "backend",
    "dtype",
    "matrix_size",
    "flops_gflops",
    "time_seconds",
    "iterations",
    "os",
    "python_version",
    "torch_version",
    "cuda_version",
]

ALLOWED_BACKENDS = {"cpu", "cuda", "mps", "xpu", "opencl", "ocl"}
ALLOWED_DTYPES = {
    "N/A",
    "FP64",
    "FP32",
    "FP16",
    "BF16",
    "FP8_exp",
    "INT8",
    "float64",
    "float32",
    "float16",
    "bfloat16",
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
HOSTNAME_RE = re.compile(r"\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")
USER_PATH_RE = re.compile(r"([\\/](?:Users|home)[\\/])[^\\/]+", flags=re.IGNORECASE)
WHITESPACE_RE = re.compile(r"\s+")


@dataclass
class IngestSummary:
    processed_count: int = 0
    accepted_count: int = 0
    rejected_count: int = 0
    duplicate_count: int = 0
    queue_line_count: int = 0


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def normalize_text(value: Any, max_len: int = 160) -> str:
    text = str(value if value is not None else "").strip()
    text = WHITESPACE_RE.sub(" ", text)
    return text[:max_len]


def sanitize_text(value: Any, max_len: int = 160) -> str:
    text = normalize_text(value, max_len=max_len)
    text = EMAIL_RE.sub("[redacted-email]", text)
    text = IPV4_RE.sub("[redacted-ip]", text)
    text = HOSTNAME_RE.sub("[redacted-host]", text)
    text = USER_PATH_RE.sub(r"\1[redacted-user]", text)
    return text[:max_len]


def normalize_backend(value: Any) -> str:
    return normalize_text(value, max_len=32).lower()


def normalize_dtype(value: Any) -> str:
    raw = normalize_text(value, max_len=32)
    if raw.upper() in {"NA", "N/A"}:
        return "N/A"
    return raw


def parse_timestamp(value: Any) -> str:
    raw = normalize_text(value, max_len=64)
    if not raw:
        raise ValueError("missing timestamp")
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt.isoformat()


def parse_int(value: Any, field: str, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"invalid {field}: not an integer") from exc
    if parsed < min_value or parsed > max_value:
        raise ValueError(f"invalid {field}: out of range [{min_value}, {max_value}]")
    return parsed


def parse_float(value: Any, field: str, min_value: float, max_value: float) -> float:
    try:
        parsed = float(value)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"invalid {field}: not a float") from exc
    if parsed < min_value or parsed > max_value:
        raise ValueError(f"invalid {field}: out of range [{min_value}, {max_value}]")
    return parsed


def normalize_cuda_version(value: Any) -> str:
    raw = normalize_text(value, max_len=32)
    if raw in {"", "N/A", "None", "nan", "NaN"}:
        return "N/A"
    try:
        val = float(raw)
        if val < 0:
            raise ValueError
        return str(val).rstrip("0").rstrip(".")
    except Exception:  # noqa: BLE001
        return raw


def extract_submission(raw_record: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(raw_record, dict):
        raise ValueError("record is not a JSON object")

    if isinstance(raw_record.get("submission"), dict):
        return raw_record["submission"]

    client_payload = raw_record.get("client_payload")
    if isinstance(client_payload, dict):
        if isinstance(client_payload.get("submission"), dict):
            return client_payload["submission"]
        return client_payload

    return raw_record


def validate_submission(submission: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(submission, dict):
        raise ValueError("submission is not a JSON object")

    missing = [field for field in CSV_COLUMNS if field not in submission]
    if missing:
        raise ValueError(f"missing required fields: {', '.join(missing)}")

    row: Dict[str, Any] = {}

    row["timestamp"] = parse_timestamp(submission["timestamp"])
    row["cpu_model"] = sanitize_text(submission["cpu_model"])
    row["cpu_cores"] = parse_int(submission["cpu_cores"], "cpu_cores", 1, 2048)
    row["cpu_frequency"] = normalize_text(submission["cpu_frequency"], max_len=64) or "Unknown"
    row["gpu_vendor"] = sanitize_text(submission["gpu_vendor"], max_len=64) or "N/A"
    row["gpu_model"] = sanitize_text(submission["gpu_model"], max_len=128) or "N/A"
    row["gpu_memory_gb"] = round(parse_float(submission["gpu_memory_gb"], "gpu_memory_gb", 0.0, 10000.0), 2)
    row["gpu_compute_capability"] = sanitize_text(submission["gpu_compute_capability"], max_len=32) or "N/A"
    row["benchmark_name"] = normalize_text(submission["benchmark_name"], max_len=128)
    row["benchmark_type"] = normalize_text(submission["benchmark_type"], max_len=64).lower()
    row["backend"] = normalize_backend(submission["backend"])
    row["dtype"] = normalize_dtype(submission["dtype"])
    row["matrix_size"] = parse_int(submission["matrix_size"], "matrix_size", 0, 1_000_000)
    row["flops_gflops"] = round(parse_float(submission["flops_gflops"], "flops_gflops", 0.000001, 1_000_000_000.0), 2)
    row["time_seconds"] = round(parse_float(submission["time_seconds"], "time_seconds", 0.000001, 3600.0), 6)
    row["iterations"] = parse_int(submission["iterations"], "iterations", 1, 1_000_000_000)
    row["os"] = sanitize_text(submission["os"], max_len=128)
    row["python_version"] = normalize_text(submission["python_version"], max_len=32)
    row["torch_version"] = normalize_text(submission["torch_version"], max_len=32)
    row["cuda_version"] = normalize_cuda_version(submission["cuda_version"])

    if row["backend"] not in ALLOWED_BACKENDS:
        raise ValueError(f"invalid backend: {row['backend']}")

    if row["dtype"] not in ALLOWED_DTYPES:
        raise ValueError(f"invalid dtype: {row['dtype']}")

    if row["benchmark_type"] == "":
        raise ValueError("benchmark_type must not be empty")

    if not (
        row["benchmark_type"] in {"gpu", "cpu_single_core", "cpu_single_core_blas", "cpu_all_cores"}
        or row["benchmark_type"].startswith("cpu_")
    ):
        raise ValueError(f"invalid benchmark_type: {row['benchmark_type']}")

    if row["backend"] == "cpu" and not row["benchmark_type"].startswith("cpu"):
        raise ValueError("cpu backend requires cpu_* benchmark_type")

    if row["backend"] != "cpu" and row["benchmark_type"].startswith("cpu"):
        raise ValueError("non-cpu backend cannot use cpu_* benchmark_type")

    return row


def _safe_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return fallback


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:  # noqa: BLE001
        return fallback


def fingerprint_row(row: Dict[str, Any]) -> str:
    timestamp = normalize_text(row.get("timestamp", ""), max_len=32)
    date_part = timestamp[:10]
    key = {
        "date": date_part,
        "cpu_model": sanitize_text(row.get("cpu_model", ""), max_len=128).lower(),
        "cpu_cores": _safe_int(row.get("cpu_cores", 0)),
        "gpu_vendor": sanitize_text(row.get("gpu_vendor", ""), max_len=64).lower(),
        "gpu_model": sanitize_text(row.get("gpu_model", ""), max_len=128).lower(),
        "benchmark_type": sanitize_text(row.get("benchmark_type", ""), max_len=64).lower(),
        "backend": sanitize_text(row.get("backend", ""), max_len=32).lower(),
        "dtype": normalize_dtype(row.get("dtype", "")),
        "matrix_size": _safe_int(row.get("matrix_size", 0)),
        "flops_gflops": round(_safe_float(row.get("flops_gflops", 0.0)), 2),
        "iterations": _safe_int(row.get("iterations", 0)),
    }
    payload = json.dumps(key, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_existing_fingerprints(csv_path: Path) -> Set[str]:
    fingerprints: Set[str] = set()
    if not csv_path.exists():
        return fingerprints

    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            try:
                fingerprints.add(fingerprint_row(row))
            except Exception:  # noqa: BLE001
                continue
    return fingerprints


def ensure_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("", encoding="utf-8")


def append_csv_rows(csv_path: Path, rows: Iterable[Dict[str, Any]]) -> int:
    materialized = list(rows)
    if not materialized:
        return 0

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = csv_path.exists()
    with csv_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        if not file_exists:
            writer.writeheader()
        for row in materialized:
            writer.writerow(row)
    return len(materialized)


def append_ndjson(path: Path, records: Iterable[Dict[str, Any]]) -> int:
    materialized = list(records)
    if not materialized:
        return 0
    ensure_file(path)
    with path.open("a", encoding="utf-8") as handle:
        for record in materialized:
            handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True))
            handle.write("\n")
    return len(materialized)


def read_pending(path: Path, max_pending: int) -> List[Tuple[int, str]]:
    ensure_file(path)
    lines: List[Tuple[int, str]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            lines.append((line_no, stripped))
            if len(lines) >= max_pending:
                break
    return lines


def drop_processed_lines(path: Path, last_line_no: int) -> None:
    """Rewrite the pending file keeping only lines after *last_line_no*.

    read_pending() consumes at most ``max_pending`` non-empty lines, so
    blanking the whole file would silently discard the unread remainder (and
    any rows appended concurrently during ingest).
    """
    ensure_file(path)
    with path.open("r", encoding="utf-8") as handle:
        remaining = handle.readlines()[last_line_no:]
    path.write_text("".join(remaining), encoding="utf-8")


def write_log(path: Path, summary: IngestSummary, accepted_rows: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp_utc": utc_now_iso(),
        "processed_count": summary.processed_count,
        "accepted_count": summary.accepted_count,
        "rejected_count": summary.rejected_count,
        "duplicate_count": summary.duplicate_count,
        "queue_line_count": summary.queue_line_count,
        "csv_rows_appended": accepted_rows,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def process(
    pending_file: Path,
    csv_path: Path,
    rejected_file: Path,
    log_file: Path,
    max_pending: int,
) -> IngestSummary:
    summary = IngestSummary()
    pending_lines = read_pending(pending_file, max_pending=max_pending)
    summary.queue_line_count = len(pending_lines)

    if not pending_lines:
        print("No pending submissions.")
        return summary

    existing_fingerprints = load_existing_fingerprints(csv_path)
    batch_fingerprints: Set[str] = set()
    accepted_rows: List[Dict[str, Any]] = []
    rejected_records: List[Dict[str, Any]] = []

    for line_no, raw_line in pending_lines:
        summary.processed_count += 1
        try:
            raw_record = json.loads(raw_line)
        except json.JSONDecodeError:
            summary.rejected_count += 1
            rejected_records.append(
                {
                    "timestamp_utc": utc_now_iso(),
                    "line": line_no,
                    "reason": "invalid JSON",
                    "raw": raw_line,
                }
            )
            continue

        try:
            submission = extract_submission(raw_record)
            row = validate_submission(submission)
        except Exception as exc:  # noqa: BLE001
            summary.rejected_count += 1
            rejected_records.append(
                {
                    "timestamp_utc": utc_now_iso(),
                    "line": line_no,
                    "reason": str(exc),
                    "raw": raw_record,
                }
            )
            continue

        fp = fingerprint_row(row)
        if fp in existing_fingerprints or fp in batch_fingerprints:
            summary.duplicate_count += 1
            continue

        batch_fingerprints.add(fp)
        accepted_rows.append(row)
        summary.accepted_count += 1

    appended_count = append_csv_rows(csv_path, accepted_rows)
    append_ndjson(rejected_file, rejected_records)
    # Drop only the lines we actually read; keep any beyond max_pending.
    drop_processed_lines(pending_file, pending_lines[-1][0])
    write_log(log_file, summary, appended_count)

    print(
        "Ingest summary: "
        f"processed={summary.processed_count} "
        f"accepted={summary.accepted_count} "
        f"duplicates={summary.duplicate_count} "
        f"rejected={summary.rejected_count} "
        f"appended={appended_count}"
    )
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest benchmark submissions from NDJSON queue")
    parser.add_argument("--pending-file", type=Path, default=Path("data/pending_submissions.ndjson"))
    parser.add_argument("--csv-path", type=Path, default=Path("benchmark_results.csv"))
    parser.add_argument("--rejected-file", type=Path, default=Path("data/rejected_submissions.ndjson"))
    parser.add_argument("--log-file", type=Path, default=Path("data/ingest_log.json"))
    parser.add_argument("--max-pending", type=int, default=5000)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.max_pending < 1:
        raise SystemExit("--max-pending must be >= 1")

    process(
        pending_file=args.pending_file,
        csv_path=args.csv_path,
        rejected_file=args.rejected_file,
        log_file=args.log_file,
        max_pending=args.max_pending,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
