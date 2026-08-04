#!/usr/bin/env python3
"""Audit and fix bilingual Hugo content for language consistency.

Three-phase pipeline:
  1. SCAN  — detect language mismatches, missing counterparts, broken YAML
  2. AUDIT — use Claude CLI to review flagged files and decide action
  3. FIX   — re-translate via Ollama for files Claude flags as broken

Usage:
    python scripts/audit_content_languages.py --scan              # Phase 1 only (fast)
    python scripts/audit_content_languages.py --scan --audit      # Phase 1 + 2
    python scripts/audit_content_languages.py --fix               # All three phases
    python scripts/audit_content_languages.py --fix --dry-run     # Preview fixes
    python scripts/audit_content_languages.py --scan --dir tools/website/content  # Specific dir
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from common.llm import call_llm_raw
from common.translation import (
    _scan_frontmatter_fields,
    detect_language,
    sanitize_frontmatter_language,
    split_frontmatter,
    translate_markdown_document,
    wrong_language,
    zh_path,
)

logger = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────────────────

BODY_MIN_LENGTH = 50        # skip very short files

IssueKind = Literal[
    "zh_low_cjk",       # .zh.md has too little Chinese
    "en_high_cjk",      # .md has too much Chinese
    "missing_zh",        # .md exists but .zh.md is missing
    "missing_en",        # .zh.md exists but .md is missing
    "yaml_error",        # frontmatter has syntax issues
    "prompt_leak",       # translation artifact in content
    "fm_lang",           # title/summary/keywords in the wrong language
]

ISSUE_LABELS = {
    "zh_low_cjk": "Chinese file contains mostly English",
    "en_high_cjk": "English file contains Chinese content",
    "missing_zh": "Missing Chinese counterpart (.zh.md)",
    "missing_en": "Missing English counterpart (.md)",
    "yaml_error": "YAML frontmatter syntax error",
    "prompt_leak": "Translation prompt leaked into content",
    "fm_lang": "Frontmatter field in the wrong language",
}


@dataclass
class Issue:
    kind: IssueKind
    path: Path
    detail: str = ""
    cjk_ratio: float = 0.0
    audit_verdict: str = ""  # "retranslate", "ok", "manual"


@dataclass
class AuditResult:
    issues: list[Issue] = field(default_factory=list)
    scanned: int = 0


# ─── Phase 1: Scan ──────────────────────────────────────────────────

def _extract_body(text: str) -> str:
    """Strip YAML frontmatter, return body only."""
    parts = text.split("---", 2)
    return parts[2].strip() if len(parts) >= 3 else text.strip()


def _extract_frontmatter(text: str) -> str:
    """Extract raw YAML frontmatter string."""
    parts = text.split("---", 2)
    return parts[1].strip() if len(parts) >= 3 else ""


def _cjk_ratio(text: str) -> float:
    if not text:
        return 0.0
    cjk = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return cjk / len(text)


def _has_prompt_leak(text: str) -> bool:
    """Detect leaked translation prompts."""
    head = text[:600].lower()
    markers = ["---begin---", "---end---", "only translate:", "rules:\n1.",
               "professional translator", "return only the translated"]
    return any(m in head for m in markers)


def _check_yaml_frontmatter(text: str, path: Path) -> str | None:
    """Return error description if YAML frontmatter has obvious issues."""
    fm = _extract_frontmatter(text)
    if not fm:
        return None

    for i, line in enumerate(fm.split("\n"), start=2):
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("-") or line_stripped.startswith("#"):
            continue

        # Check for nested unescaped double quotes in double-quoted values
        match = re.match(r'^(\w+):\s*"(.+)"$', line_stripped)
        if match:
            value = match.group(2)
            # If value contains unescaped double quotes (not at boundaries)
            if '"' in value:
                return f"line {i}: nested double quotes in '{match.group(1)}' field"

    return None


def _zh_counterpart(path: Path) -> Path:
    """Get .zh.md path from .md path."""
    return path.parent / f"{path.stem}.zh{path.suffix}"


def _en_counterpart(zh_path: Path) -> Path:
    """Get .md path from .zh.md path."""
    stem = zh_path.stem  # e.g. "foo.zh"
    if stem.endswith(".zh"):
        stem = stem[:-3]
    return zh_path.parent / f"{stem}{zh_path.suffix}"


def scan_directory(root: Path) -> AuditResult:
    """Phase 1: Scan for language issues."""
    result = AuditResult()
    en_files: dict[str, Path] = {}
    zh_files: dict[str, Path] = {}

    all_md = sorted(root.rglob("*.md"))
    for f in all_md:
        if f.name.startswith("_index"):
            continue
        result.scanned += 1
        rel = str(f.relative_to(root))

        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # Classify as en or zh file
        if ".zh.md" in f.name:
            key = rel.replace(".zh.md", ".md")
            zh_files[key] = f
        else:
            en_files[rel] = f
            key = rel

        # Check YAML frontmatter
        yaml_err = _check_yaml_frontmatter(text, f)
        if yaml_err:
            result.issues.append(Issue(
                kind="yaml_error", path=f,
                detail=yaml_err,
            ))

        # Check for prompt leak
        if _has_prompt_leak(text):
            result.issues.append(Issue(
                kind="prompt_leak", path=f,
                detail="Translation prompt markers found in content",
            ))

        # Frontmatter language — the body check below can't see it, yet Hugo
        # renders title/keywords right at the top of every page.
        expected = "zh" if ".zh.md" in f.name else "en"
        frontmatter, _ = split_frontmatter(text)
        _, wrong_fields = _scan_frontmatter_fields(
            frontmatter, predicate=lambda v: detect_language(v) != expected,
            include_labels=expected == "en",
        )
        if wrong_fields:
            keys = ", ".join(sorted({fld[1].strip().rstrip(":") or "-" for fld in wrong_fields}))
            result.issues.append(Issue(
                kind="fm_lang", path=f,
                detail=f"expected {expected}, wrong in: {keys}",
            ))

        # Check the body's language. Judged on prose only (wrong_language strips
        # code/HTML/URLs first): a raw CJK ratio over the whole body is diluted
        # to near-zero by an embedded component like the summarize usage-card,
        # which hid nine fully-Chinese English daily reports from this scan.
        body = _extract_body(text)
        if len(body) < BODY_MIN_LENGTH:
            continue

        ratio = _cjk_ratio(body)

        if wrong_language(body, expected):
            result.issues.append(Issue(
                kind="zh_low_cjk" if expected == "zh" else "en_high_cjk", path=f,
                detail=f"body prose is not {expected} (CJK ratio {ratio:.3f})",
                cjk_ratio=ratio,
            ))

    # Check for missing counterparts
    for key, en_path in en_files.items():
        if key not in zh_files:
            result.issues.append(Issue(
                kind="missing_zh", path=en_path,
                detail="No .zh.md counterpart found",
            ))

    for key, zh_path in zh_files.items():
        if key not in en_files:
            result.issues.append(Issue(
                kind="missing_en", path=zh_path,
                detail="No .md (English) counterpart found",
            ))

    return result


# ─── Phase 2: Claude Audit ──────────────────────────────────────────

AUDIT_PROMPT_TEMPLATE = """\
You are a bilingual content auditor for a Hugo blog that has English (.md) and Chinese (.zh.md) versions of each page.

I have detected the following issue with a markdown file:

**File:** {path}
**Issue type:** {issue_kind} — {issue_label}
**Detail:** {detail}

Here is the beginning of the file content (first 1500 chars):
```
{content_preview}
```

Please analyze this file and respond with EXACTLY one JSON object (no other text):
{{
  "verdict": "<retranslate|ok|manual>",
  "reason": "<brief explanation>",
  "source_lang": "<en|zh>",
  "target_lang": "<en|zh>"
}}

Verdicts:
- "retranslate": The file needs to be re-translated from its counterpart. Set source_lang to the language of the GOOD counterpart and target_lang to the language this file SHOULD be in.
- "ok": The file is actually fine despite the flag (e.g., code-heavy content legitimately has low CJK).
- "manual": The issue requires human review (e.g., both versions are wrong).

Be conservative — only say "ok" if the content is genuinely acceptable for its intended language."""


def audit_issues(issues: list[Issue], root: Path, *, backend: str = "claude_cli") -> None:
    """Phase 2: Use Claude to review each flagged file."""
    auditable = [i for i in issues if i.kind in (
        "zh_low_cjk", "en_high_cjk", "prompt_leak",
    )]

    if not auditable:
        print("  No issues require Claude audit.")
        return

    print(f"\n  Auditing {len(auditable)} files with Claude...")

    for issue in auditable:
        try:
            text = issue.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            issue.audit_verdict = "manual"
            continue

        preview = text[:1500]
        prompt = AUDIT_PROMPT_TEMPLATE.format(
            path=issue.path.relative_to(root) if issue.path.is_relative_to(root) else issue.path,
            issue_kind=issue.kind,
            issue_label=ISSUE_LABELS[issue.kind],
            detail=issue.detail,
            content_preview=preview,
        )

        try:
            response = call_llm_raw(prompt, backend=backend, model="haiku", timeout=120)
            # Extract JSON from response
            json_match = re.search(r"\{[^{}]*\}", response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                issue.audit_verdict = data.get("verdict", "manual")
                issue.detail += f" | Claude: {data.get('reason', '')}"
            else:
                issue.audit_verdict = "manual"
                issue.detail += " | Claude: could not parse response"
        except Exception as e:
            logger.warning("Claude audit failed for %s: %s", issue.path.name, e)
            issue.audit_verdict = "retranslate"  # default to retranslate on failure
            issue.detail += f" | Claude audit error: {e}"

        verdict_display = issue.audit_verdict.upper()
        print(f"    [{verdict_display}] {issue.path.name} — {issue.detail}")


# ─── Phase 3: Fix ───────────────────────────────────────────────────

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        from common.engine import create_engine
        _engine = create_engine()
        _engine.load()
    return _engine


def _close_engine():
    global _engine
    if _engine is not None:
        _engine.unload()
        _engine = None


def fix_issues(issues: list[Issue], *, dry_run: bool = False) -> tuple[int, int]:
    """Phase 3: Re-translate files that need fixing."""
    to_fix = [i for i in issues if i.audit_verdict == "retranslate"
              or i.kind in ("missing_zh", "missing_en", "yaml_error", "fm_lang")]
    if not to_fix:
        print("  No files need fixing.")
        return 0, 0

    fixed, failed = 0, 0

    for issue in to_fix:
        path = issue.path

        if issue.kind == "fm_lang":
            # Frontmatter only — the body is fine, so don't pay for (or risk)
            # a whole-document re-translation.
            expected = "zh" if ".zh.md" in path.name else "en"
            if dry_run:
                print(f"    [dry-run] fix {expected} frontmatter in {path.name}")
                fixed += 1
                continue
            try:
                text = path.read_text(encoding="utf-8")
                out = sanitize_frontmatter_language(text, expected, _get_engine())
                if out != text:
                    path.write_text(out, encoding="utf-8")
                print(f"    [fixed] frontmatter in {path.name}")
                fixed += 1
            except Exception as e:
                print(f"    [error] {path.name}: {e}")
                failed += 1
            continue

        if issue.kind == "yaml_error":
            # Fix YAML by switching outer quotes to single quotes
            ok = _fix_yaml_quotes(path, dry_run=dry_run)
            if ok:
                fixed += 1
            else:
                failed += 1
            continue

        # Determine source and target for translation
        if issue.kind == "zh_low_cjk" or issue.kind == "missing_zh":
            # zh.md is bad or missing — translate from en.md → zh
            if issue.kind == "missing_zh":
                source_path = path  # path IS the en file
                target_path = _zh_counterpart(path)
            else:
                target_path = path  # path IS the zh file
                source_path = _en_counterpart(path)
            source_lang, target_lang = "en", "zh"
        elif issue.kind == "en_high_cjk" or issue.kind == "missing_en":
            # en.md is bad or missing — translate from zh.md → en
            if issue.kind == "missing_en":
                source_path = path  # path IS the zh file
                target_path = _en_counterpart(path)
            else:
                target_path = path  # path IS the en file
                source_path = _zh_counterpart(path)
            source_lang, target_lang = "zh", "en"
        elif issue.kind == "prompt_leak":
            # Determine from file name which direction
            if ".zh.md" in path.name:
                source_path = _en_counterpart(path)
                target_path = path
                source_lang, target_lang = "en", "zh"
            else:
                source_path = _zh_counterpart(path)
                target_path = path
                source_lang, target_lang = "zh", "en"
        else:
            continue

        if not source_path.exists():
            print(f"    [skip] source {source_path.name} not found for {target_path.name}")
            failed += 1
            continue

        if dry_run:
            print(f"    [dry-run] {source_path.name} ({source_lang}) → {target_path.name} ({target_lang})")
            fixed += 1
            continue

        try:
            source_text = source_path.read_text(encoding="utf-8")
            translated = translate_markdown_document(
                source_text, source_lang, target_lang,
                engine=_get_engine(),
            )
            target_path.write_text(translated, encoding="utf-8")
            print(f"    [fixed] {source_path.name} → {target_path.name}")
            fixed += 1
        except Exception as e:
            print(f"    [error] {target_path.name}: {e}")
            failed += 1

    return fixed, failed


def _fix_yaml_quotes(path: Path, *, dry_run: bool = False) -> bool:
    """Fix nested double quotes in YAML frontmatter by switching to single quotes."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False

    parts = text.split("---", 2)
    if len(parts) < 3:
        return False

    fm_lines = parts[1].split("\n")
    changed = False

    for i, line in enumerate(fm_lines):
        stripped = line.strip()
        match = re.match(r'^(\w+):\s*"(.+)"$', stripped)
        if match and '"' in match.group(2):
            key = match.group(1)
            value = match.group(2)
            # Remove markdown bold markers for YAML safety
            clean_value = value.replace("**", "")
            indent = line[:len(line) - len(line.lstrip())]
            fm_lines[i] = f"{indent}{key}: '{clean_value}'"
            changed = True

    if not changed:
        return False

    if dry_run:
        print(f"    [dry-run] fix YAML quotes in {path.name}")
        return True

    new_text = "---".join([parts[0], "\n".join(fm_lines), parts[2]])
    path.write_text(new_text, encoding="utf-8")
    print(f"    [fixed] YAML quotes in {path.name}")
    return True


# ─── Main ────────────────────────────────────────────────────────────

def print_report(result: AuditResult, root: Path) -> None:
    """Print a summary of all issues found."""
    print(f"\n{'='*60}")
    print(f"  Content Language Audit Report")
    print(f"  Root: {root}")
    print(f"  Files scanned: {result.scanned}")
    print(f"  Issues found: {len(result.issues)}")
    print(f"{'='*60}\n")

    if not result.issues:
        print("  All files look good!")
        return

    by_kind: dict[str, list[Issue]] = {}
    for issue in result.issues:
        by_kind.setdefault(issue.kind, []).append(issue)

    for kind, issues in by_kind.items():
        print(f"  [{kind}] {ISSUE_LABELS[kind]} ({len(issues)} files)")
        for issue in issues:
            rel = issue.path.relative_to(root) if issue.path.is_relative_to(root) else issue.path
            verdict = f" → {issue.audit_verdict}" if issue.audit_verdict else ""
            print(f"    - {rel}: {issue.detail}{verdict}")
        print()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="Audit and fix bilingual Hugo content for language consistency",
    )
    parser.add_argument("--scan", action="store_true", help="Phase 1: scan for issues")
    parser.add_argument("--audit", action="store_true", help="Phase 2: Claude reviews flagged files")
    parser.add_argument("--fix", action="store_true", help="All phases: scan + audit + fix")
    parser.add_argument("--dry-run", action="store_true", help="Preview fixes without writing")
    parser.add_argument("--dir", type=Path, help="Scan a specific directory")
    parser.add_argument("--api", default="claude_cli",
                        choices=["claude_cli", "anthropic", "openai", "ollama"],
                        help="LLM backend for audit phase (default: claude_cli)")
    args = parser.parse_args()

    if not (args.scan or args.audit or args.fix):
        args.scan = True  # default to scan

    # Determine directories to scan — the single Hugo content root
    default_dirs = [
        ROOT / "tools" / "website" / "content",
    ]
    dirs = [args.dir] if args.dir else default_dirs

    all_issues: list[Issue] = []
    total_scanned = 0

    for d in dirs:
        if not d.is_dir():
            print(f"[skip] {d} does not exist")
            continue

        print(f"\n--- Scanning: {d} ---")
        result = scan_directory(d)
        total_scanned += result.scanned

        print_report(result, d)

        if (args.audit or args.fix) and result.issues:
            audit_issues(result.issues, d, backend=args.api)

        all_issues.extend(result.issues)

    # Phase 3: Fix
    if args.fix and all_issues:
        print(f"\n{'='*60}")
        print(f"  Phase 3: Fixing issues")
        print(f"{'='*60}\n")
        try:
            fixed, failed = fix_issues(all_issues, dry_run=args.dry_run)
        finally:
            _close_engine()

        label = "[dry-run] " if args.dry_run else ""
        print(f"\n  {label}Fixed: {fixed}, Failed: {failed}")

    # Summary
    print(f"\n{'='*60}")
    print(f"  Total files scanned: {total_scanned}")
    print(f"  Total issues: {len(all_issues)}")
    by_kind = {}
    for i in all_issues:
        by_kind.setdefault(i.kind, 0)
        by_kind[i.kind] += 1
    for kind, count in by_kind.items():
        print(f"    {kind}: {count}")
    print(f"{'='*60}")

    return 1 if all_issues else 0


if __name__ == "__main__":
    sys.exit(main())
