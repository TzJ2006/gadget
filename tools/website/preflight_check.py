#!/usr/bin/env python3
"""Pre-build readiness check for the Hugo website.

Runs between media compression (Step 6) and Hugo build (Step 8) in the
publish pipeline. Checks modified files since .last_build for:

1. Uncompressed images (.jpg/.jpeg remaining)
2. Stale links (../../static references not rewritten)
3. Frontmatter YAML validity
4. Bilingual pair completeness (.md ↔ .zh.md) — auto-generates missing pair
5. Language correctness (en body in .md, zh body in .zh.md) — auto-fixes

Language-aware pair generation (Check 4):
  - foo.md exists with Chinese content → copy to foo.zh.md, translate foo.md to English
  - foo.md exists with English content → translate to generate foo.zh.md
  - foo.zh.md exists with English content → copy to foo.md, translate foo.zh.md to Chinese
  - foo.zh.md exists with Chinese content → translate to generate foo.md

Tiered severity:
  - BLOCK  → exit 1, stops build (frontmatter errors)
  - WARN   → printed but build continues (stale links, images)
  - FIX    → auto-repaired via translation engine (missing pairs, language mismatch)

Exit codes: 0 = clean, 1 = blocking errors, 2 = warnings only
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import yaml
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any

SITE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = SITE_ROOT.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from common.translation import detect_language

STALE_LINK_PATTERN = re.compile(r"\.\./\.\./static")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?\n)---\s*\n?(.*)$", re.DOTALL)
MIN_BODY_LENGTH = 100

# Pipeline-managed content (deploy pipelines write these with complete bilingual
# pairs + gadget markers via common.bilingual/site_staging) — preflight trusts
# them and only checks hand-written content. Auto-"fixing" a generated file
# would desync it from its src-hash marker and cause churn on the next deploy.
GENERATED_CONTENT_DIRS = ("bugJournal/daily", "bugJournal/weekly",
                          "bugJournal/monthly", "research")
GENERATED_CONTENT_FILES = ("benchmark.md", "benchmark.zh.md")


@dataclass
class Issue:
    level: str  # BLOCK, WARN, FIX
    check: str
    path: str
    detail: str
    extra: dict[str, Any] = field(default_factory=dict)


def get_last_build_time(timestamp_file: Path) -> float:
    if timestamp_file.exists():
        return timestamp_file.stat().st_mtime
    return 0.0


def _is_generated(path: Path, root: Path) -> bool:
    try:
        rel = path.relative_to(root).as_posix()
    except ValueError:
        return False
    if rel in GENERATED_CONTENT_FILES:
        return True
    return any(rel.startswith(d + "/") for d in GENERATED_CONTENT_DIRS)


def find_modified_files(directory: Path, since: float, suffix: str = ".md") -> list[Path]:
    if not directory.exists():
        return []
    results = []
    for path in directory.rglob(f"*{suffix}"):
        if path.name.startswith("._"):
            continue
        if _is_generated(path, directory):
            continue
        if path.stat().st_mtime > since:
            results.append(path)
    return sorted(results)


def find_modified_images(image_dir: Path, since: float) -> list[Path]:
    if not image_dir.exists():
        return []
    results = []
    for ext in ("*.jpg", "*.jpeg"):
        for path in image_dir.rglob(ext):
            if path.name.startswith("._"):
                continue
            if path.stat().st_mtime > since:
                results.append(path)
    return sorted(results)


def is_zh_file(path: Path) -> bool:
    return path.stem.endswith(".zh")


def counterpart_path(path: Path) -> Path:
    if path.stem.endswith(".zh"):
        return path.with_name(path.stem[:-3] + path.suffix)
    return path.with_name(f"{path.stem}.zh{path.suffix}")


def split_frontmatter_raw(content: str) -> tuple[str, str]:
    match = FRONTMATTER_RE.match(content)
    if match:
        return content[: match.end(1) + 4], match.group(2)  # includes --- delimiters
    return "", content


# ── Check 1: Uncompressed images ─────────────────────────────────────

def check_images(image_dir: Path, since: float) -> list[Issue]:
    images = find_modified_images(image_dir, since)
    return [
        Issue("WARN", "image", str(img), "JPEG file not converted to PNG")
        for img in images
    ]


# ── Check 2: Stale links ─────────────────────────────────────────────

def check_stale_links(files: list[Path]) -> list[Issue]:
    issues: list[Issue] = []
    for path in files:
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue
        for i, line in enumerate(content.splitlines(), start=1):
            if STALE_LINK_PATTERN.search(line):
                issues.append(
                    Issue("WARN", "link", f"{path}:{i}", "../../static reference not rewritten")
                )
    return issues


# ── Check 3: Frontmatter validation ──────────────────────────────────

def check_frontmatter(files: list[Path]) -> list[Issue]:
    issues: list[Issue] = []
    for path in files:
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as exc:
            issues.append(Issue("BLOCK", "frontmatter", str(path), f"cannot read file: {exc}"))
            continue

        match = FRONTMATTER_RE.match(content)
        if not match:
            issues.append(Issue("BLOCK", "frontmatter", str(path), "missing frontmatter delimiters"))
            continue

        raw_yaml = match.group(1)
        try:
            parsed = yaml.safe_load(raw_yaml)
        except yaml.YAMLError as exc:
            issues.append(Issue("BLOCK", "frontmatter", str(path), f"YAML parse error: {exc}"))
            continue

        if not isinstance(parsed, dict):
            issues.append(Issue("BLOCK", "frontmatter", str(path), "frontmatter is not a YAML mapping"))
            continue

        if "title" not in parsed:
            issues.append(Issue("BLOCK", "frontmatter", str(path), "missing required field: title"))
    return issues


# ── Check 4: Bilingual pair completeness ──────────────────────────────

def check_bilingual_pairs(files: list[Path]) -> list[Issue]:
    """Detect missing counterpart files and determine fix strategy.

    extra fields for FIX issues:
      - existing_path: path of the file that exists
      - missing_path: path of the file to generate
      - existing_lang: detected language of the existing file's body
      - slot: "en" or "zh" — which slot the existing file occupies
      - needs_swap: True if content language doesn't match the file slot
    """
    issues: list[Issue] = []
    seen: set[str] = set()

    for path in files:
        partner = counterpart_path(path)
        norm_key = str(min(path, partner))
        if norm_key in seen:
            continue
        seen.add(norm_key)

        if partner.exists():
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            issues.append(Issue("WARN", "pair", str(path), f"missing counterpart: {partner.name}"))
            continue

        match = FRONTMATTER_RE.match(content)
        body = match.group(2) if match else content
        detected_lang = detect_language(body) if len(body.strip()) >= MIN_BODY_LENGTH else None
        slot = "zh" if is_zh_file(path) else "en"

        if detected_lang and detected_lang != slot:
            needs_swap = True
            detail = (
                f"missing {partner.name}; {path.name} contains {detected_lang} "
                f"content → will copy to correct slot and translate"
            )
        else:
            needs_swap = False
            detail = f"missing {partner.name} → will translate from {path.name}"

        issues.append(Issue(
            "FIX", "pair", str(path), detail,
            extra={
                "existing_path": str(path),
                "missing_path": str(partner),
                "existing_lang": detected_lang or slot,
                "slot": slot,
                "needs_swap": needs_swap,
            },
        ))
    return issues


# ── Check 5: Language correctness ─────────────────────────────────────

def check_language(files: list[Path]) -> list[Issue]:
    issues: list[Issue] = []
    checked_paths: set[str] = set()

    for path in files:
        if not path.exists() or not counterpart_path(path).exists():
            continue

        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            continue

        match = FRONTMATTER_RE.match(content)
        if not match:
            continue

        raw_yaml_str, body = match.group(1), match.group(2)
        expected = "zh" if is_zh_file(path) else "en"

        if len(body.strip()) < MIN_BODY_LENGTH:
            continue

        detected = detect_language(body)
        if detected != expected:
            issues.append(Issue(
                "FIX", "language", str(path),
                f"expected {expected} body but detected {detected}",
            ))
            checked_paths.add(str(path))
            continue

        try:
            parsed = yaml.safe_load(raw_yaml_str)
        except Exception:
            continue
        title = parsed.get("title", "") if isinstance(parsed, dict) else ""
        if title and len(title) > 5:
            title_lang = detect_language(title)
            if title_lang != expected and str(path) not in checked_paths:
                issues.append(Issue(
                    "FIX", "language", str(path),
                    f"title language mismatch: expected {expected} but detected {title_lang}",
                ))
    return issues


# ── Auto-fix engine ───────────────────────────────────────────────────

def _load_translation_engine():
    from common.engine import create_engine, DEFAULT_TRANSLATION_MODEL
    engine = create_engine(DEFAULT_TRANSLATION_MODEL)
    engine.load()
    return engine


def _translate_full_document(engine, content: str, target_lang: str) -> str:
    from common.translation import translate_markdown_document
    source_lang = "zh" if target_lang == "en" else "en"
    return translate_markdown_document(content, source_lang, target_lang, engine=engine)


def fix_pair_issues(pair_fixes: list[Issue], engine) -> tuple[int, int]:
    fixed = 0
    failed = 0

    for issue in pair_fixes:
        ex = issue.extra
        existing = Path(ex["existing_path"])
        missing = Path(ex["missing_path"])
        needs_swap = ex["needs_swap"]
        existing_lang = ex["existing_lang"]

        try:
            content = existing.read_text(encoding="utf-8")

            if needs_swap:
                correct_slot = missing if (
                    (existing_lang == "zh" and is_zh_file(missing))
                    or (existing_lang == "en" and not is_zh_file(missing))
                ) else existing

                if correct_slot == missing:
                    shutil.copy2(str(existing), str(missing))
                    target_lang = "en" if is_zh_file(missing) else "zh"
                    translated = _translate_full_document(engine, content, target_lang)
                    existing.write_text(translated, encoding="utf-8")
                    print(f"  [fix] {existing.name} (was {existing_lang}) → copied to {missing.name}, translated {existing.name}")
                else:
                    target_lang = "zh" if is_zh_file(missing) else "en"
                    translated = _translate_full_document(engine, content, target_lang)
                    missing.write_text(translated, encoding="utf-8")
                    print(f"  [fix] translated {existing.name} → {missing.name}")
            else:
                target_lang = "zh" if is_zh_file(missing) else "en"
                translated = _translate_full_document(engine, content, target_lang)
                missing.write_text(translated, encoding="utf-8")
                print(f"  [fix] translated {existing.name} → {missing.name}")

            fixed += 1
        except Exception as exc:
            print(f"  [fail] could not fix pair for {existing.name}: {exc}")
            failed += 1

    return fixed, failed


def fix_language_issues(lang_fixes: list[Issue], engine) -> tuple[int, int]:
    fixed = 0
    failed = 0

    for issue in lang_fixes:
        path = Path(issue.path)
        expected = "zh" if is_zh_file(path) else "en"

        try:
            content = path.read_text(encoding="utf-8")
            new_content = _translate_full_document(engine, content, expected)
            path.write_text(new_content, encoding="utf-8")
            print(f"  [fix] repaired language: {path.name}")
            fixed += 1
        except Exception as exc:
            print(f"  [fail] could not fix {path.name}: {exc}")
            failed += 1

    return fixed, failed


def run_auto_fixes(pair_fixes: list[Issue], lang_fixes: list[Issue]) -> tuple[int, int]:
    all_fixes = pair_fixes + lang_fixes
    if not all_fixes:
        return 0, 0

    try:
        engine = _load_translation_engine()
    except ImportError:
        print("  [skip] translation engine not available, cannot auto-fix")
        return 0, len(all_fixes)
    except Exception as exc:
        print(f"  [skip] could not load translation engine: {exc}")
        return 0, len(all_fixes)

    total_fixed = 0
    total_failed = 0

    try:
        if pair_fixes:
            f, e = fix_pair_issues(pair_fixes, engine)
            total_fixed += f
            total_failed += e

        if lang_fixes:
            f, e = fix_language_issues(lang_fixes, engine)
            total_fixed += f
            total_failed += e
    finally:
        engine.unload()

    return total_fixed, total_failed


# ── Main ──────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preflight readiness check for Hugo website")
    parser.add_argument("--content-dir", default="content", help="Content directory (default: content)")
    parser.add_argument("--image-dir", default="static/images", help="Image directory (default: static/images)")
    parser.add_argument("--timestamp-file", default=".last_build", help="Timestamp file (default: .last_build)")
    parser.add_argument("--no-fix", action="store_true", help="Skip auto-fix, report only")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    content_dir = SITE_ROOT / args.content_dir
    image_dir = SITE_ROOT / args.image_dir
    timestamp_file = SITE_ROOT / args.timestamp_file

    since = get_last_build_time(timestamp_file)
    modified_md = find_modified_files(content_dir, since, ".md")

    if not modified_md and not find_modified_images(image_dir, since):
        print("  [ok] no modified files to check")
        return 0

    if args.verbose:
        print(f"  checking {len(modified_md)} modified .md files")

    all_issues: list[Issue] = []

    all_issues.extend(check_images(image_dir, since))
    all_issues.extend(check_stale_links(modified_md))
    all_issues.extend(check_frontmatter(modified_md))
    all_issues.extend(check_bilingual_pairs(modified_md))
    all_issues.extend(check_language(modified_md))

    blocks = [i for i in all_issues if i.level == "BLOCK"]
    warns = [i for i in all_issues if i.level == "WARN"]
    pair_fixes = [i for i in all_issues if i.level == "FIX" and i.check == "pair"]
    lang_fixes = [i for i in all_issues if i.level == "FIX" and i.check == "language"]

    for issue in blocks:
        print(f"  ✘ BLOCK [{issue.check}] {issue.path}: {issue.detail}")
    for issue in warns:
        print(f"  ⚠ WARN  [{issue.check}] {issue.path}: {issue.detail}")
    for issue in pair_fixes + lang_fixes:
        print(f"  ⟳ FIX   [{issue.check}] {issue.path}: {issue.detail}")

    total_fixed = 0
    total_fix_failed = 0
    if (pair_fixes or lang_fixes) and not args.no_fix:
        print(f"  → auto-fixing {len(pair_fixes)} pair + {len(lang_fixes)} language issues ...")
        total_fixed, total_fix_failed = run_auto_fixes(pair_fixes, lang_fixes)
        print(f"  → fixed={total_fixed} failed={total_fix_failed}")

    total = len(blocks) + len(warns) + len(pair_fixes) + len(lang_fixes)
    if total == 0:
        print("  [ok] all preflight checks passed")
        return 0

    summary_parts = []
    if blocks:
        summary_parts.append(f"{len(blocks)} blocking")
    if warns:
        summary_parts.append(f"{len(warns)} warnings")
    fix_count = len(pair_fixes) + len(lang_fixes)
    if total_fixed:
        summary_parts.append(f"{total_fixed} auto-fixed")
    elif fix_count:
        summary_parts.append(f"{fix_count} fixable")
    if total_fix_failed:
        summary_parts.append(f"{total_fix_failed} fix-failed")
    print(f"  [{total} issues: {', '.join(summary_parts)}]")

    if blocks:
        print("  ✘ BUILD BLOCKED — fix the above errors before deploying")
        return 1

    return 2 if warns else 0


if __name__ == "__main__":
    sys.exit(main())
