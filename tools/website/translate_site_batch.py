#!/usr/bin/env python3
"""Incrementally synchronize English/Chinese Hugo markdown pairs.

Uses local inference (vLLM on Linux, transformers on Windows) for translation.
Supports two canonical file shapes:
  - English/default: foo.md
  - Chinese:         foo.zh.md

The script is designed for pre-build use in website/update.sh:
  - backfill missing counterparts,
  - detect which side changed since the last successful sync,
  - avoid en<->zh translation ping-pong via a local state file.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SITE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = SITE_ROOT.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from common.engine import TranslationEngine, create_engine, DEFAULT_TRANSLATION_MODEL
from common.io import atomic_write, content_hash
from common.translation import (
    LANG_NAMES,
    detect_language,
    split_frontmatter,
    translate_markdown_document,
)

logger = logging.getLogger(__name__)

MODEL_ID = DEFAULT_TRANSLATION_MODEL
STATE_FILE = SITE_ROOT / ".translation_state.json"
STATE_VERSION = 1


@dataclass(slots=True)
class FileInfo:
    path: Path
    content: str
    language: str
    digest: str
    mtime_ns: int


@dataclass(slots=True)
class PairInfo:
    key: str
    en_path: Path
    zh_path: Path
    en_file: FileInfo | None
    zh_file: FileInfo | None


@dataclass(slots=True)
class Operation:
    pair_key: str
    source_lang: str
    target_lang: str
    source_path: Path
    canonical_source_path: Path
    target_path: Path
    source_content: str
    reason: str
    warnings: list[str] = field(default_factory=list)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Incrementally translate Hugo markdown into English and Chinese",
    )
    parser.add_argument(
        "--root",
        action="append",
        required=True,
        help="Content root to scan for markdown files. May be passed multiple times.",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="File or directory to exclude from translation scanning.",
    )
    parser.add_argument(
        "--state-file",
        default=str(STATE_FILE),
        help=f"Path to the translation state file (default: {STATE_FILE.name})",
    )
    parser.add_argument(
        "--model",
        default=MODEL_ID,
        help=f"Translation model (default: {MODEL_ID})",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Force retranslating pairs even when both language files already exist.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show planned work without writing files or loading the model.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging.",
    )
    return parser.parse_args()


def canonical_en_path(path: Path) -> Path:
    if path.name.endswith(".zh.md"):
        return path.with_name(path.name[: -len(".zh.md")] + ".md")
    if path.name.endswith(".en.md"):
        return path.with_name(path.name[: -len(".en.md")] + ".md")
    return path


def canonical_zh_path(en_path: Path) -> Path:
    return en_path.with_name(f"{en_path.stem}.zh{en_path.suffix}")


def is_excluded(path: Path, excluded: list[Path]) -> bool:
    return any(path == item or item in path.parents for item in excluded)


def read_file_info(path: Path) -> FileInfo | None:
    if not path.exists() or not path.is_file():
        return None

    content = path.read_text(encoding="utf-8")
    _, body = split_frontmatter(content)
    language = detect_language(body or content)
    return FileInfo(
        path=path,
        content=content,
        language=language,
        digest=content_hash(content, length=32),
        mtime_ns=path.stat().st_mtime_ns,
    )


def collect_pairs(root: Path, excluded: list[Path]) -> tuple[dict[str, PairInfo], list[str]]:
    warnings: list[str] = []
    pairs: dict[str, PairInfo] = {}

    if not root.exists():
        warnings.append(f"[skip] root not found: {root}")
        return pairs, warnings

    for path in sorted(root.rglob("*.md")):
        resolved = path.resolve()
        if is_excluded(resolved, excluded):
            continue
        if path.name.endswith(".en.md"):
            warnings.append(f"[skip] unsupported legacy filename, leaving untouched: {path}")
            continue

        en_path = canonical_en_path(resolved)
        zh_path = canonical_zh_path(en_path)
        key = str(en_path)
        pair = pairs.get(key)
        if pair is None:
            pair = PairInfo(
                key=key,
                en_path=en_path,
                zh_path=zh_path,
                en_file=None,
                zh_file=None,
            )
            pairs[key] = pair

        info = read_file_info(resolved)
        if info is None:
            continue
        if resolved == zh_path:
            pair.zh_file = info
        else:
            pair.en_file = info

    return pairs, warnings


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": STATE_VERSION, "pairs": {}}

    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning("State file is unreadable, starting fresh: %s", path)
        return {"version": STATE_VERSION, "pairs": {}}

    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        logger.warning("State file version mismatch, starting fresh: %s", path)
        return {"version": STATE_VERSION, "pairs": {}}
    if not isinstance(state.get("pairs"), dict):
        state["pairs"] = {}
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    atomic_write(path, json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def is_valid_pair(pair: PairInfo) -> bool:
    return (
        pair.en_file is not None
        and pair.zh_file is not None
        and pair.en_file.language == "en"
        and pair.zh_file.language == "zh"
    )


def newer_file(*files: FileInfo | None) -> FileInfo:
    existing = [item for item in files if item is not None]
    return max(existing, key=lambda item: item.mtime_ns)


def choose_source_from_state(pair: PairInfo, state_entry: dict[str, Any] | None) -> FileInfo:
    candidates = [item for item in (pair.en_file, pair.zh_file) if item is not None]
    if not candidates:
        raise ValueError("No files available for source selection")

    if state_entry:
        changed: list[FileInfo] = []
        for info in candidates:
            if info.path == pair.en_path:
                previous = state_entry.get("en_sha256")
            elif info.path == pair.zh_path:
                previous = state_entry.get("zh_sha256")
            else:
                previous = None
            if previous != info.digest:
                changed.append(info)

        if len(changed) == 1:
            return changed[0]
        if changed:
            return newer_file(*changed)

    return newer_file(*candidates)


def state_entry_for_pair(
    en_digest: str,
    zh_digest: str,
    source_lang: str,
) -> dict[str, Any]:
    return {
        "en_sha256": en_digest,
        "zh_sha256": zh_digest,
        "last_source_lang": source_lang,
        "updated_at": int(time.time()),
    }


def build_operation(
    pair: PairInfo,
    source: FileInfo,
    reason: str,
    warnings: list[str] | None = None,
) -> Operation:
    source_lang = source.language
    target_lang = "zh" if source_lang == "en" else "en"
    canonical_source_path = pair.en_path if source_lang == "en" else pair.zh_path
    target_path = pair.zh_path if source_lang == "en" else pair.en_path
    return Operation(
        pair_key=pair.key,
        source_lang=source_lang,
        target_lang=target_lang,
        source_path=source.path,
        canonical_source_path=canonical_source_path,
        target_path=target_path,
        source_content=source.content,
        reason=reason,
        warnings=list(warnings or []),
    )


def plan_pair(
    pair: PairInfo,
    state_entry: dict[str, Any] | None,
    force_full: bool,
) -> tuple[Operation | None, dict[str, Any] | None, list[str]]:
    warnings: list[str] = []

    if pair.en_file is None and pair.zh_file is None:
        return None, None, warnings

    if is_valid_pair(pair):
        if force_full:
            source_lang = state_entry.get("last_source_lang") if state_entry else None
            if source_lang == "zh":
                source = pair.zh_file
            elif source_lang == "en":
                source = pair.en_file
            else:
                source = newer_file(pair.en_file, pair.zh_file)
            return build_operation(pair, source, "forced full retranslation"), None, warnings

        if state_entry is None:
            bootstrap = state_entry_for_pair(
                pair.en_file.digest,
                pair.zh_file.digest,
                newer_file(pair.en_file, pair.zh_file).language,
            )
            return None, bootstrap, warnings

        changed_en = state_entry.get("en_sha256") != pair.en_file.digest
        changed_zh = state_entry.get("zh_sha256") != pair.zh_file.digest

        if not changed_en and not changed_zh:
            return None, state_entry, warnings

        if changed_en and not changed_zh:
            return build_operation(pair, pair.en_file, "english source changed"), None, warnings
        if changed_zh and not changed_en:
            return build_operation(pair, pair.zh_file, "chinese source changed"), None, warnings

        warnings.append(
            f"[warn] both sides changed, using newer file as source: {pair.en_path.name}",
        )
        return build_operation(pair, newer_file(pair.en_file, pair.zh_file), "both sides changed"), None, warnings

    source = choose_source_from_state(pair, state_entry)
    if pair.en_file and pair.en_file.language != "en":
        warnings.append(f"[warn] {pair.en_path} contains {pair.en_file.language} content")
    if pair.zh_file and pair.zh_file.language != "zh":
        warnings.append(f"[warn] {pair.zh_path} contains {pair.zh_file.language} content")
    return build_operation(pair, source, "missing or inconsistent language pair", warnings), None, warnings


def translate_document(
    content: str,
    target_lang: str,
    engine: TranslationEngine,
) -> str:
    source_lang = "zh" if target_lang == "en" else "en"
    return translate_markdown_document(content, source_lang, target_lang, engine=engine)


def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(message)s",
    )

    roots = [Path(item).resolve() for item in args.root]
    excluded = [Path(item).resolve() for item in args.exclude]
    state_path = Path(args.state_file).resolve()
    state = load_state(state_path)
    state_pairs: dict[str, Any] = dict(state.get("pairs", {}))

    pair_map: dict[str, PairInfo] = {}
    scan_warnings: list[str] = []
    for root in roots:
        pairs, warnings = collect_pairs(root, excluded)
        pair_map.update(pairs)
        scan_warnings.extend(warnings)

    for warning in scan_warnings:
        print(warning)

    operations: list[Operation] = []
    bootstrap_updates: dict[str, Any] = {}

    for pair_key, pair in sorted(pair_map.items()):
        op, bootstrap, warnings = plan_pair(pair, state_pairs.get(pair_key), args.full)
        for warning in warnings:
            print(warning)
        if bootstrap is not None:
            bootstrap_updates[pair_key] = bootstrap
        if op is not None:
            operations.append(op)

    if args.dry_run:
        print(f"[dry-run] scanned {len(pair_map)} pairs")
        for op in operations:
            print(
                f"[plan] {op.reason}: {op.source_path} ({op.source_lang}) -> "
                f"{op.target_path} ({op.target_lang})",
            )
        if not operations:
            print("[dry-run] no translation work needed")
        return 0

    if not operations:
        if bootstrap_updates:
            state_pairs.update(bootstrap_updates)
            state["pairs"] = state_pairs
            save_state(state_path, state)
            print(f"[ok] translation state bootstrapped for {len(bootstrap_updates)} pairs")
        else:
            print("[ok] no translation work needed")
        return 0

    try:
        engine = create_engine(args.model)
        engine.load()
    except Exception as exc:
        print(f'[warn] could not load translation model "{args.model}": {exc}')
        print('[warn] continuing without translation updates')
        if bootstrap_updates:
            state_pairs.update(bootstrap_updates)
            state["pairs"] = state_pairs
            save_state(state_path, state)
        return 0

    translated = 0
    failed = 0

    try:
        for index, op in enumerate(operations, start=1):
            print(
                f"[{index}/{len(operations)}] {op.reason}: "
                f"{op.source_path.name} ({op.source_lang}) -> {op.target_path.name} ({op.target_lang})",
            )
            try:
                if op.canonical_source_path != op.source_path:
                    atomic_write(op.canonical_source_path, op.source_content)
                    print(f"  [ok] canonical source updated: {op.canonical_source_path}")

                translated_content = translate_document(op.source_content, op.target_lang, engine)
                atomic_write(op.target_path, translated_content)

                if op.source_lang == "en":
                    en_digest = content_hash(op.source_content, length=32)
                    zh_digest = content_hash(translated_content, length=32)
                else:
                    en_digest = content_hash(translated_content, length=32)
                    zh_digest = content_hash(op.source_content, length=32)

                state_pairs[op.pair_key] = state_entry_for_pair(
                    en_digest,
                    zh_digest,
                    op.source_lang,
                )
                translated += 1
                print(f"  [ok] wrote {op.target_path}")
            except Exception as exc:
                failed += 1
                print(f"  [warn] translation failed for {op.source_path}: {exc}")
                logger.debug(traceback.format_exc())
    finally:
        engine.unload()

    for pair_key, bootstrap in bootstrap_updates.items():
        state_pairs.setdefault(pair_key, bootstrap)

    state["pairs"] = state_pairs
    save_state(state_path, state)

    print(
        f"[done] translated={translated} failed={failed} "
        f"bootstrapped={len(bootstrap_updates)} total_pairs={len(pair_map)}",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
