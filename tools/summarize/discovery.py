"""Canonical known-location discovery; no conversation text or models are read."""

from __future__ import annotations

import os
import platform
from pathlib import Path


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def home_dirs(wsl_release: str | None = None, wsl_users: Path | None = None) -> list[Path]:
    """Real home, plus Windows user homes when running under WSL."""
    homes = [Path.home()]
    release = platform.uname().release if wsl_release is None else wsl_release
    if "microsoft" in release.lower():
        root = Path("/mnt/c/Users") if wsl_users is None else wsl_users
        if _is_dir(root):
            try:
                homes.extend(item for item in root.iterdir() if _is_dir(item))
            except OSError:
                pass
    return homes


def claude_project_dirs(homes: list[Path], override: str = "") -> list[Path]:
    if override:
        return [Path(override)]
    found = []
    for home in homes:
        try:
            candidates = sorted(home.glob(".claude*"))
        except OSError:
            continue
        for candidate in candidates:
            projects = candidate / "projects"
            try:
                exists = projects.is_dir()
            except OSError:
                found.append(projects)
                continue
            if exists:
                found.append(projects)
    return _dedupe(found)


def codex_session_dirs(homes: list[Path], override: str = "") -> list[Path]:
    if override:
        return [Path(override)]
    return _dedupe([home / ".codex" / "sessions" for home in homes if _is_dir(home / ".codex" / "sessions")])


def cursor_transcript_roots(homes: list[Path], override: str = "") -> list[Path]:
    if override:
        return [Path(override)]
    roots = []
    for home in homes:
        projects = home / ".cursor" / "projects"
        if not _is_dir(projects):
            continue
        try:
            children = list(projects.iterdir())
        except OSError:
            continue
        for project in children:
            transcripts = project / "agent-transcripts"
            if _is_dir(transcripts):
                roots.append(transcripts)
    return _dedupe(roots)


def iter_cursor_parent_jsonl(transcript_root: Path):
    """Yield parent transcripts only. Layout: <root>/<id>/<id>.jsonl. Skips subagents."""
    try:
        entries = list(transcript_root.iterdir())
    except OSError:
        return
    for conv_dir in entries:
        if not _is_dir(conv_dir):
            continue
        if conv_dir.name == "subagents" or "subagents" in conv_dir.parts:
            continue
        jsonl = conv_dir / f"{conv_dir.name}.jsonl"
        try:
            if jsonl.is_file():
                yield jsonl.resolve()
        except OSError:
            continue


def discover_sources(
    *,
    homes: list[Path] | None = None,
    claude_root: str = "",
    codex_root: str = "",
    cursor_root: str = "",
    chatgpt_export: str = "",
    wsl_release: str | None = None,
    wsl_users: Path | None = None,
) -> list[dict]:
    """List known locations. Does not read conversation text or call a model."""
    homes = list(homes) if homes is not None else home_dirs(wsl_release, wsl_users)
    rows = []
    rows.extend(
        _describe(
            "claude_code",
            "Claude Code JSONL logs (not a Claude app export)",
            claude_project_dirs(homes, claude_root),
            "*.jsonl",
        )
    )
    rows.extend(
        _describe("codex", "Codex session logs", codex_session_dirs(homes, codex_root), "*.jsonl")
    )
    cursor_dirs = cursor_transcript_roots(homes, cursor_root)
    if cursor_dirs:
        for path in cursor_dirs:
            rows.append(_cursor_row(path))
    elif cursor_root:
        rows.append(_missing("cursor", "Cursor agent transcripts", cursor_root))
    else:
        rows.append(_missing("cursor", "Cursor agent transcripts", ""))
    export = (chatgpt_export or "").strip()
    if export:
        path = Path(export)
        try:
            exists = path.is_file()
        except OSError:
            rows.append(_status("chatgpt", "ChatGPT conversations.json", path, "unreadable", ""))
        else:
            status = "found" if exists else "missing"
            rows.append(_status("chatgpt", "ChatGPT conversations.json", path, status, "1" if exists else "0"))
    else:
        rows.append(
            {
                "source": "chatgpt",
                "label": "ChatGPT conversations.json",
                "path": "",
                "status": "missing",
                "count": "0",
                "detail": "No fixed export location. Choose the conversations.json file.",
            }
        )
    return rows


def _describe(source: str, label: str, paths: list[Path], pattern: str) -> list[dict]:
    if not paths:
        return [_missing(source, label, "")]
    rows = []
    for path in paths:
        try:
            if path.is_dir():
                rows.append(_status(source, label, path, "found", _count(path, pattern)))
            else:
                rows.append(_status(source, label, path, "missing", "0"))
        except OSError:
            rows.append(_status(source, label, path, "unreadable", ""))
    return rows


def _cursor_row(path: Path) -> dict:
    try:
        count = sum(1 for _ in iter_cursor_parent_jsonl(path))
        status = "found"
        text = str(count)
    except OSError:
        status = "unreadable"
        text = ""
    return _status("cursor", "Cursor agent transcripts", path, status, text)


def _missing(source: str, label: str, path: str) -> dict:
    return {
        "source": source,
        "label": label,
        "path": path,
        "status": "missing",
        "count": "0",
        "detail": "",
    }


def _status(source: str, label: str, path: Path, status: str, count: str) -> dict:
    try:
        shown = str(path.resolve()) if str(path) else ""
    except OSError:
        shown = str(path)
        status = "unreadable"
    return {
        "source": source,
        "label": label,
        "path": shown,
        "status": status,
        "count": count,
        "detail": "",
    }


def _count(root: Path, pattern: str, limit: int = 200) -> str:
    found = 0
    try:
        for item in root.rglob(pattern):
            if "subagents" in item.parts:
                continue
            found += 1
            if found >= limit:
                return f"{limit}+"
    except OSError:
        return ""
    return str(found)


def _existing(paths: list[Path]) -> list[Path]:
    found = []
    for path in paths:
        try:
            if path.is_dir():
                found.append(path)
            elif not path.exists():
                continue
        except OSError:
            continue
    return _dedupe(found)


def _dedupe(paths: list[Path]) -> list[Path]:
    seen = set()
    unique = []
    for path in paths:
        try:
            key = os.path.normcase(str(path.resolve()))
        except OSError:
            continue
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique
