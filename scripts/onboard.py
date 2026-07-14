#!/usr/bin/env python3
"""Repo-wide onboarding — fill one sheet, run one script.

Reads a YAML "sheet" (default ``tokens/onboard.yaml``) and runs a set of
independent, idempotent onboarding steps. Each sheet section has an ``enabled:``
flag, so a given machine only runs the steps it needs. Safe actions apply
automatically; risky ones (SSH key drops, pushing keys to remote hosts, extra
global npm) prompt first unless ``--yes``.

Steps live in an ordered registry (``STEPS``). To add a new onboarding:
  1. write ``step_<name>(cfg, ctx) -> StepResult``,
  2. add ``("<name>", step_<name>)`` to ``STEPS``,
  3. add a ``<name>:`` section with ``enabled:`` to ``scripts/onboard.example.yaml``.
Nothing in the core run loop changes.

Usage:
    python scripts/onboard.py [--sheet PATH] [--only a,b] [--skip a,b]
                              [--dry-run] [--yes] [--no-verify]
                              [--verify-only] [--list]
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

GADGET_ROOT = Path(__file__).resolve().parent.parent

# Make tool packages importable when run as a plain script. The editable install
# (`pip install -e .`) normally covers this; we *append* (never prepend) so we
# don't shadow installed packages or trip the stale-root-dir issue.
for _p in (GADGET_ROOT / "tools", GADGET_ROOT):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.append(_ps)

IS_WINDOWS = platform.system() == "Windows"
SSH_DIR = Path("~/.ssh").expanduser()
SSH_CONFIG = SSH_DIR / "config"
# User-level Claude Code settings (every OS). NOT the repo's project .claude/settings.json
# (which carries the dev hooks) — secrets belong here, outside the repo.
CLAUDE_USER_SETTINGS = Path("~/.claude/settings.json").expanduser()
SENTINEL = "managed-by: gadget-onboard"
DEFAULT_SHEET = GADGET_ROOT / "tokens" / "onboard.yaml"
EXAMPLE_SHEET = GADGET_ROOT / "scripts" / "onboard.example.yaml"

# Every Claude auth env var any mode might set. We strip all of these from the
# existing settings before applying the chosen mode, so a previous run's mode
# can't shadow the new one (Bedrock/Foundry otherwise take precedence).
ALL_MODE_VARS = [
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_USE_BEDROCK", "AWS_REGION", "AWS_PROFILE",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "AWS_BEARER_TOKEN_BEDROCK",
    "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL",
    "CLAUDE_CODE_USE_ANTHROPIC_AWS", "ANTHROPIC_AWS_WORKSPACE_ID",
    "ANTHROPIC_AWS_API_KEY", "ANTHROPIC_AWS_BASE_URL",
]
MODE_MARKER_VARS = {
    "api": ["ANTHROPIC_API_KEY"],
    "bedrock": ["CLAUDE_CODE_USE_BEDROCK"],
    "platform_aws": ["CLAUDE_CODE_USE_ANTHROPIC_AWS"],
}


@dataclass
class Ctx:
    """Uniform context handed to every step."""

    dry_run: bool
    assume_yes: bool
    sheet: dict = field(default_factory=dict)


@dataclass
class StepResult:
    name: str
    status: str  # "ok" | "skipped" | "failed"
    detail: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _run(cmd, *, dry_run, timeout=900, cwd=None, stdin=None) -> bool:
    """Run a subprocess (output streams to console). Returns True on success.

    Never pass secrets in *cmd* — they would be printed. Use *stdin* for any
    sensitive payload (the only such payload here is a *public* key).
    """
    print(f"  $ {' '.join(str(c) for c in cmd)}")
    if dry_run:
        return True
    try:
        result = subprocess.run(cmd, text=True, timeout=timeout, cwd=cwd, input=stdin)
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"  [error] {e}")
        return False
    if result.returncode != 0:
        print(f"  [error] command exited with {result.returncode}")
        return False
    return True


def _confirm(prompt, *, assume_yes) -> bool:
    if assume_yes:
        return True
    try:
        return input(f"  ? {prompt} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _which(name):
    return shutil.which(name)


def _non_empty(d: dict) -> dict:
    """Drop keys whose value is an empty string or None (so defaults apply)."""
    return {k: v for k, v in d.items() if v not in ("", None)}


def _expand(p) -> Path:
    """Expand ~ and resolve repo-relative paths (e.g. tokens/...) against root."""
    path = Path(str(p)).expanduser()
    return path if path.is_absolute() else (GADGET_ROOT / path)


def _harden(path: Path, mode: int) -> None:
    """Restrict permissions: chmod on POSIX, icacls on Windows (best-effort)."""
    if IS_WINDOWS:
        user = os.environ.get("USERNAME")
        if not user:
            return
        try:
            subprocess.run(
                ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
                capture_output=True, text=True, timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            print(f"  [warn] icacls on {path} failed: {e}")
        return
    try:
        os.chmod(path, mode)
    except OSError as e:
        print(f"  [warn] chmod {oct(mode)} {path} failed: {e}")


def _load_sheet(path: Path) -> dict:
    import yaml

    if not path.exists():
        print(f"[error] onboarding sheet not found: {path}")
        print("  Copy the template and fill it in:")
        print(f"    cp {EXAMPLE_SHEET} {path}")
        sys.exit(1)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        print(f"[error] sheet must be a YAML mapping: {path}")
        sys.exit(1)
    return data


def _write_json_config(path: Path, desired: dict, *, dry_run: bool) -> str:
    """Merge *desired* into an existing JSON config. Returns 'ok' or 'skipped'."""
    from common.io import atomic_write, load_json_config

    existing = load_json_config(path)
    merged = {**existing, **desired}
    if merged == existing:
        print(f"  [skip] {path} already up to date")
        return "skipped"
    print(f"  [write] {path}")
    if not dry_run:
        atomic_write(path, json.dumps(merged, indent=2, ensure_ascii=False) + "\n")
    return "ok"


# ---------------------------------------------------------------------------
# Step: ssh  (both directions — local config/keys + push to remote)
# ---------------------------------------------------------------------------


def _ssh_block(host: dict) -> str:
    alias = host["alias"]
    lines = [f"# {SENTINEL} >>> {alias}", f"Host {alias}"]
    if host.get("hostname"):
        lines.append(f"    HostName {host['hostname']}")
    if host.get("user"):
        lines.append(f"    User {host['user']}")
    if host.get("port"):
        lines.append(f"    Port {host['port']}")
    if host.get("identity_file"):
        lines.append(f"    IdentityFile {host['identity_file']}")
    lines.append(f"# {SENTINEL} <<< {alias}")
    return "\n".join(lines)


def _upsert_ssh_config(host: dict, *, dry_run: bool) -> bool:
    """Write/replace a sentinel-fenced block for *host* in ~/.ssh/config.

    Lines outside the fence are never touched. Returns True if it changed.
    """
    from common.io import atomic_write

    alias = host["alias"]
    block = _ssh_block(host)
    existing = SSH_CONFIG.read_text(encoding="utf-8") if SSH_CONFIG.exists() else ""
    pattern = re.compile(
        rf"# {re.escape(SENTINEL)} >>> {re.escape(alias)}\n.*?"
        rf"# {re.escape(SENTINEL)} <<< {re.escape(alias)}",
        re.DOTALL,
    )
    if pattern.search(existing):
        new = pattern.sub(lambda _m: block, existing)
    else:
        prefix = existing
        if prefix and not prefix.endswith("\n"):
            prefix += "\n"
        if prefix:
            prefix += "\n"
        new = prefix + block + "\n"

    if new == existing:
        print(f"  [skip] ~/.ssh/config entry for '{alias}' up to date")
        return False
    print(f"  [write] ~/.ssh/config entry for '{alias}'")
    if not dry_run:
        SSH_DIR.mkdir(parents=True, exist_ok=True)
        _harden(SSH_DIR, 0o700)
        if existing and SENTINEL not in existing:
            bak = SSH_CONFIG.with_name(SSH_CONFIG.name + ".bak")
            if not bak.exists():
                bak.write_text(existing, encoding="utf-8")
                print(f"  [backup] {bak}")
        atomic_write(SSH_CONFIG, new)
        _harden(SSH_CONFIG, 0o600)
    return True


def _install_private_key(ipk: dict, ctx: Ctx) -> None:
    from common.io import atomic_write

    if not ipk.get("from") or not ipk.get("to"):
        print("  [warn] install_private_key needs 'from' and 'to'; skipping")
        return
    src, dst = _expand(ipk["from"]), _expand(ipk["to"])
    if not src.is_file():
        print(f"  [warn] private key source not found: {src}")
        return
    src_text = src.read_text(encoding="utf-8")
    if dst.exists() and dst.read_text(encoding="utf-8") == src_text:
        print(f"  [skip] private key already installed at {dst}")
        return
    if ctx.dry_run:
        print(f"  [dry-run] would install private key -> {dst} (chmod 600, after prompt)")
        return
    if not _confirm(f"install private key {src} -> {dst} (chmod 600)?", assume_yes=ctx.assume_yes):
        print("  [skip] declined private key install")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(dst, src_text)
    _harden(dst, 0o600)
    pub_src = src.with_name(src.name + ".pub")
    if pub_src.is_file():
        pub_dst = dst.with_name(dst.name + ".pub")
        atomic_write(pub_dst, pub_src.read_text(encoding="utf-8"))
        _harden(pub_dst, 0o644)
    print(f"  [ok] installed private key -> {dst}")


def _push_public_key(host: dict, ctx: Ctx) -> None:
    alias = host["alias"]
    pub = host.get("public_key")
    if not pub and host.get("identity_file"):
        pub = str(host["identity_file"]) + ".pub"
    if not pub:
        print(f"  [warn] no public_key for '{alias}'; skipping push")
        return
    pub_path = _expand(pub)
    if not pub_path.is_file():
        print(f"  [warn] public key not found: {pub_path}")
        return
    pub_line = pub_path.read_text(encoding="utf-8").strip()
    if ctx.dry_run:
        print(f"  [dry-run] would push public key to {alias}:~/.ssh/authorized_keys (after prompt)")
        return
    # Idempotency: skip if the remote already has this key.
    check = subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", alias,
         f"grep -qsF '{pub_line}' ~/.ssh/authorized_keys"],
        capture_output=True, text=True,
    )
    if check.returncode == 0:
        print(f"  [skip] '{alias}' already has this public key")
        return
    if not _confirm(f"push public key to {alias}:~/.ssh/authorized_keys?", assume_yes=ctx.assume_yes):
        print("  [skip] declined key push")
        return
    # Portable ssh-copy-id (no ssh-copy-id needed; works on Windows too).
    ok = _run(
        ["ssh", alias, "umask 077; mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys"],
        dry_run=False, stdin=pub_line + "\n",
    )
    print(f"  [ok] pushed public key to {alias}" if ok else f"  [error] push to {alias} failed")


def step_ssh(cfg: dict, ctx: Ctx) -> StepResult:
    hosts = cfg.get("hosts") or []
    if not hosts:
        return StepResult("ssh", "skipped", "no hosts listed")
    for host in hosts:
        if not host.get("alias"):
            print("  [warn] host entry without 'alias'; skipping")
            continue
        _upsert_ssh_config(host, dry_run=ctx.dry_run)
        if host.get("install_private_key"):
            _install_private_key(host["install_private_key"], ctx)
        if host.get("push_public_key"):
            _push_public_key(host, ctx)
    return StepResult("ssh", "ok", f"{len(hosts)} host(s) processed")


# ---------------------------------------------------------------------------
# Step: claude  (install CLIs + write auth env)
# ---------------------------------------------------------------------------


def _ensure_cli(name: str, npm_pkgs: list[str], ctx: Ctx) -> None:
    found = _which(name)
    if found:
        print(f"  [skip] {name} already installed ({found})")
        return
    npm = _which("npm")
    if not npm:
        print(f"  [warn] npm not found; cannot install {name} (install Node.js first)")
        return
    _run([npm, "install", "-g", *npm_pkgs], dry_run=ctx.dry_run)


def _build_env_block(mode: str, cfg: dict) -> dict:
    """Return the exact Claude Code env vars for *mode*, dropping empty values."""
    if mode == "api":
        api = cfg.get("api") or {}
        return _non_empty({"ANTHROPIC_API_KEY": api.get("ANTHROPIC_API_KEY", "")})
    if mode == "bedrock":
        b = cfg.get("bedrock") or {}
        env = {"CLAUDE_CODE_USE_BEDROCK": "1"}
        env.update(_non_empty({
            "AWS_REGION": b.get("AWS_REGION", ""),
            "AWS_PROFILE": b.get("AWS_PROFILE", ""),
            "AWS_ACCESS_KEY_ID": b.get("AWS_ACCESS_KEY_ID", ""),
            "AWS_SECRET_ACCESS_KEY": b.get("AWS_SECRET_ACCESS_KEY", ""),
            "AWS_SESSION_TOKEN": b.get("AWS_SESSION_TOKEN", ""),
            "AWS_BEARER_TOKEN_BEDROCK": b.get("AWS_BEARER_TOKEN_BEDROCK", ""),
            "ANTHROPIC_DEFAULT_OPUS_MODEL": b.get("ANTHROPIC_DEFAULT_OPUS_MODEL", ""),
            "ANTHROPIC_DEFAULT_SONNET_MODEL": b.get("ANTHROPIC_DEFAULT_SONNET_MODEL", ""),
            "ANTHROPIC_DEFAULT_HAIKU_MODEL": b.get("ANTHROPIC_DEFAULT_HAIKU_MODEL", ""),
        }))
        return env
    if mode == "platform_aws":
        p = cfg.get("platform_aws") or {}
        env = {"CLAUDE_CODE_USE_ANTHROPIC_AWS": "1"}
        env.update(_non_empty({
            "ANTHROPIC_AWS_WORKSPACE_ID": p.get("ANTHROPIC_AWS_WORKSPACE_ID", ""),
            "AWS_REGION": p.get("AWS_REGION", ""),
            "ANTHROPIC_AWS_API_KEY": p.get("ANTHROPIC_AWS_API_KEY", ""),
            "ANTHROPIC_AWS_BASE_URL": p.get("ANTHROPIC_AWS_BASE_URL", ""),
        }))
        return env
    raise ValueError(f"unknown auth_mode: {mode!r} (use api / bedrock / platform_aws)")


def _write_claude_auth(mode: str, cfg: dict, ctx: Ctx) -> str:
    from common.io import atomic_write, load_json_config

    env_block = _build_env_block(mode, cfg)
    settings = load_json_config(CLAUDE_USER_SETTINGS)
    env = dict(settings.get("env") or {})
    for var in ALL_MODE_VARS:  # strip every mode's vars, then apply the chosen one
        env.pop(var, None)
    env.update(env_block)

    new_settings = dict(settings)
    new_settings["env"] = env
    if mode == "bedrock":
        refresh = (cfg.get("bedrock") or {}).get("awsAuthRefresh", "")
        if refresh:
            new_settings["awsAuthRefresh"] = refresh

    if new_settings == settings:
        print(f"  [skip] {CLAUDE_USER_SETTINGS} already configured for {mode}")
        return "skipped"
    print(f"  [write] {CLAUDE_USER_SETTINGS} (auth_mode={mode})")
    if not ctx.dry_run:
        atomic_write(
            CLAUDE_USER_SETTINGS,
            json.dumps(new_settings, indent=2, ensure_ascii=False) + "\n",
        )
    return "ok"


def step_claude(cfg: dict, ctx: Ctx) -> StepResult:
    detail = []
    if cfg.get("install", True):
        _ensure_cli("claude", ["@anthropic-ai/claude-code"], ctx)
        detail.append("claude")
    codex = cfg.get("codex") or {}
    if codex.get("install"):
        _ensure_cli("codex", [codex.get("package") or "@openai/codex"], ctx)
        detail.append("codex")
    mode = cfg.get("auth_mode")
    if mode:
        detail.append(f"auth={mode}:{_write_claude_auth(mode, cfg, ctx)}")
    return StepResult("claude", "ok", "; ".join(detail) or "nothing to do")


# ---------------------------------------------------------------------------
# Step: install  (pip extras + ai-companion + plugins + extra npm)
# ---------------------------------------------------------------------------


def _install_ai_companion(ctx: Ctx) -> None:
    root = Path(os.environ.get("AI_COMPANION_ROOT", GADGET_ROOT.parent / "ai-companion")).expanduser()
    script = root / "scripts" / "install.ts"
    if not script.is_file():
        print(f"  [warn] ai-companion installer not found: {script} (set AI_COMPANION_ROOT)")
        return
    npx = _which("npx")
    if not npx:
        print("  [warn] npx not found; cannot run ai-companion installer (install Node.js)")
        return
    _run([npx, "tsx", str(script), ".", "--enforce"], dry_run=ctx.dry_run, cwd=str(GADGET_ROOT))


def _install_claude_plugin(pid: str, ctx: Ctx) -> None:
    claude = _which("claude")
    if not claude:
        print(f"  [warn] claude not found; cannot install plugin {pid}")
        return
    try:
        listed = subprocess.run([claude, "plugin", "list"], capture_output=True, text=True, timeout=60)
        if pid in (listed.stdout or ""):
            print(f"  [skip] plugin already installed: {pid}")
            return
    except (OSError, subprocess.TimeoutExpired):
        pass
    if ctx.dry_run:
        print(f"  [dry-run] would install claude plugin {pid} (after prompt)")
        return
    if not _confirm(f"install claude plugin {pid}?", assume_yes=ctx.assume_yes):
        print(f"  [skip] declined plugin {pid}")
        return
    _run([claude, "plugin", "install", pid], dry_run=False)


def step_install(cfg: dict, ctx: Ctx) -> StepResult:
    detail = []
    extras = cfg.get("pip_extras") or []
    if extras:
        _run([sys.executable, "-m", "pip", "install", "-e", f".[{','.join(extras)}]"],
             dry_run=ctx.dry_run, cwd=str(GADGET_ROOT))
        detail.append(f"pip[{','.join(extras)}]")
    if cfg.get("ai_companion"):
        _install_ai_companion(ctx)
        detail.append("ai-companion")
    for pid in (cfg.get("claude_plugins") or []):
        _install_claude_plugin(pid, ctx)
    for pkg in (cfg.get("global_npm") or []):
        if ctx.dry_run:
            print(f"  [dry-run] would npm i -g {pkg} (after prompt)")
            continue
        if not _confirm(f"npm i -g {pkg}?", assume_yes=ctx.assume_yes):
            print(f"  [skip] declined npm i -g {pkg}")
            continue
        npm = _which("npm")
        if npm:
            _run([npm, "install", "-g", pkg], dry_run=False)
        else:
            print("  [warn] npm not found")
    return StepResult("install", "ok", "; ".join(detail) or "nothing to do")


# ---------------------------------------------------------------------------
# Step: gadgets  (per-tool config JSON)
# ---------------------------------------------------------------------------


def _write_research_config(rc: dict, ctx: Ctx) -> None:
    try:
        from research.config import load_config, save_config
    except Exception as e:  # research tool not installed
        print(f"  [warn] cannot import research.config ({e}); skipping research config")
        return
    desired = _non_empty(dict(rc))
    current = load_config()
    merged = {**current, **desired}
    if merged == current:
        print("  [skip] ~/.config/research/config.json already up to date")
        return
    print("  [write] ~/.config/research/config.json")
    if not ctx.dry_run:
        save_config(merged)


def step_gadgets(cfg: dict, ctx: Ctx) -> StepResult:
    done = []
    if "summarize" in cfg:
        s = cfg["summarize"] or {}
        desired = _non_empty({
            "device_name": s.get("device_name", ""),
            "logs_dir": s.get("logs_dir", ""),
            "reports_dir": s.get("reports_dir", ""),
            "rclone_remote": s.get("rclone_remote", ""),
            "rclone_path": s.get("rclone_path", ""),
            "default_api": s.get("default_api", ""),
        })
        _write_json_config(Path("~/.config/summarize/config.json").expanduser(),
                           desired, dry_run=ctx.dry_run)
        done.append("summarize")
    if "research" in cfg:
        _write_research_config(cfg["research"] or {}, ctx)
        done.append("research")
    if "research_scout" in cfg:
        _write_json_config(Path("~/.config/research_scout/config.json").expanduser(),
                           _non_empty(dict(cfg["research_scout"] or {})), dry_run=ctx.dry_run)
        done.append("research_scout")
    return StepResult("gadgets", "ok", f"configured: {', '.join(done) or 'none'}")


# ---------------------------------------------------------------------------
# Step: sync  (optional rclone bootstrap, reuses scripts/sync.py)
# ---------------------------------------------------------------------------


def step_sync(cfg: dict, ctx: Ctx) -> StepResult:
    if not cfg.get("bootstrap"):
        return StepResult("sync", "skipped", "bootstrap not requested")
    remote = cfg.get("remote") or "gdrive:gadget"
    cmd = [sys.executable, str(GADGET_ROOT / "scripts" / "sync.py"), "bootstrap", "--remote", remote]
    if cfg.get("include_tokens"):
        if ctx.dry_run or _confirm("sync bootstrap with --include-tokens (pulls API keys)?",
                                   assume_yes=ctx.assume_yes):
            cmd.append("--include-tokens")
    if ctx.dry_run:
        cmd.append("--dry-run")
    ok = _run(cmd, dry_run=False)  # sync.py honors its own --dry-run
    return StepResult("sync", "ok" if ok else "failed", f"bootstrap {remote}")


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


def _verify_extra(ctx: Ctx, RR) -> list:
    out = []
    for name, required in (("claude", True), ("codex", False)):
        found = _which(name)
        if found:
            out.append(RR(f"cli-{name}", f"{name} CLI", "ok", required, f"Found {found}"))
        else:
            out.append(RR(f"cli-{name}", f"{name} CLI", "fail" if required else "warn",
                          required, f"{name} not on PATH",
                          "Enable claude.install / claude.codex.install in the sheet"))

    mode = (ctx.sheet.get("claude") or {}).get("auth_mode")
    if mode:
        from common.io import load_json_config
        env = load_json_config(CLAUDE_USER_SETTINGS).get("env") or {}
        markers = MODE_MARKER_VARS.get(mode, [])
        if markers and all(m in env for m in markers):
            out.append(RR("claude-auth", f"Claude auth ({mode})", "ok", False,
                          f"{', '.join(markers)} set in {CLAUDE_USER_SETTINGS}"))
        else:
            out.append(RR("claude-auth", f"Claude auth ({mode})", "warn", False,
                          f"expected {markers} in {CLAUDE_USER_SETTINGS}",
                          "Re-run: python scripts/onboard.py --only claude"))

    for host in (ctx.sheet.get("ssh") or {}).get("hosts") or []:
        alias = host.get("alias")
        if not alias:
            continue
        if ctx.dry_run:
            rc = 0
        else:
            rc = subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", alias, "true"],
                                capture_output=True, text=True).returncode
        out.append(RR(f"ssh-{alias}", f"ssh {alias}", "ok" if rc == 0 else "warn", False,
                      "reachable" if rc == 0 else "not reachable (network/auth?)"))

    probe = {"summarize": "anthropic", "research": "arxiv", "benchmark": "torch", "translator": "gradio"}
    gadgets = ctx.sheet.get("gadgets") or {}
    for tool, mod in probe.items():
        if tool in gadgets:
            ok = importlib.util.find_spec(mod) is not None
            out.append(RR(f"import-{tool}", f"{tool} deps ({mod})", "ok" if ok else "warn",
                          False, "importable" if ok else f"{mod} not importable",
                          "" if ok else f"pip install -e .[{tool}]"))
    return out


def _verify_minimal(ctx: Ctx) -> bool:
    print("[onboard] verify (minimal — summarize checker unavailable):")
    ok = True
    for name, required in (("claude", True), ("codex", False)):
        p = _which(name)
        label = "OK" if p else ("FAIL" if required else "WARN")
        print(f"  [{label}] {name}: {p or 'not found'}")
        if required and not p:
            ok = False
    return ok


def step_verify(ctx: Ctx) -> bool:
    try:
        from summarize.onboarding import (
            RequirementResult, check_auto_requirements, has_blocking_failures, print_report,
        )
    except Exception as e:
        print(f"[onboard] verify: summarize checker unavailable ({e})")
        return _verify_minimal(ctx)

    api = ((ctx.sheet.get("gadgets") or {}).get("summarize") or {}).get("default_api") or "ollama"
    results = list(check_auto_requirements(api=api))
    results += _verify_extra(ctx, RequirementResult)
    print_report(results)
    return not has_blocking_failures(results)


# ---------------------------------------------------------------------------
# Registry + run loop
# ---------------------------------------------------------------------------

# Ordered registry. ADD A FUTURE ONBOARDING HERE (+ a step fn + a sheet section).
STEPS = [
    ("ssh", step_ssh),
    ("claude", step_claude),
    ("install", step_install),
    ("gadgets", step_gadgets),
    ("sync", step_sync),
]
STEP_NAMES = [name for name, _ in STEPS]


def _active_steps(sheet: dict, only, skip) -> list[str]:
    if only:
        for u in [n for n in only if n not in STEP_NAMES]:
            print(f"[warn] unknown step in --only: {u}")
        active = [n for n in STEP_NAMES if n in only]
    else:
        active = [n for n in STEP_NAMES if (sheet.get(n) or {}).get("enabled")]
    if skip:
        active = [n for n in active if n not in skip]
    return active


def run_steps(active: list[str], ctx: Ctx) -> list[StepResult]:
    results = []
    for name, fn in STEPS:
        if name not in active:
            results.append(StepResult(name, "skipped", "disabled"))
            continue
        print(f"--- {name} ---")
        try:
            results.append(fn(ctx.sheet.get(name) or {}, ctx))
        except Exception as e:  # one failing step never stops the others
            print(f"  [error] {name} failed: {e}")
            results.append(StepResult(name, "failed", str(e)))
        print()
    return results


def main() -> None:
    ap = argparse.ArgumentParser(
        description="gadget repo-wide onboarding — fill one sheet, run one script.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--sheet", help=f"path to the YAML sheet (default {DEFAULT_SHEET})")
    ap.add_argument("--only", help="run exactly these steps (comma-separated), overriding enabled")
    ap.add_argument("--skip", help="skip these steps (comma-separated)")
    ap.add_argument("--dry-run", action="store_true", help="print actions, change nothing")
    ap.add_argument("--yes", "-y", action="store_true", help="assume yes for risky prompts")
    ap.add_argument("--no-verify", action="store_true", help="skip the readiness check at the end")
    ap.add_argument("--verify-only", action="store_true", help="only run the readiness check")
    ap.add_argument("--list", action="store_true", help="list registered steps and enabled state")
    args = ap.parse_args()

    sheet_path = Path(args.sheet).expanduser() if args.sheet else DEFAULT_SHEET
    if sheet_path.exists():
        sheet = _load_sheet(sheet_path)
    elif args.list:
        sheet = {}
    else:
        _load_sheet(sheet_path)  # prints a helpful error and exits
        return

    ctx = Ctx(dry_run=args.dry_run, assume_yes=args.yes, sheet=sheet)
    only = [s.strip() for s in args.only.split(",")] if args.only else None
    skip = [s.strip() for s in args.skip.split(",")] if args.skip else None

    if args.list:
        print("Registered onboarding steps (* = enabled in sheet):")
        for name in STEP_NAMES:
            mark = "*" if (sheet.get(name) or {}).get("enabled") else " "
            print(f"  [{mark}] {name}")
        return

    if args.verify_only:
        sys.exit(0 if step_verify(ctx) else 1)

    active = _active_steps(sheet, only, skip)
    print(f"=== gadget onboarding ===  sheet: {sheet_path}")
    print(f"steps: {', '.join(active) or '(none)'}{'   [dry-run]' if args.dry_run else ''}\n")

    results = run_steps(active, ctx)

    print("=== summary ===")
    for r in results:
        print(f"  [{r.status.upper()}] {r.name}: {r.detail}")

    verify_ok = True
    if not args.no_verify:
        print()
        verify_ok = step_verify(ctx)

    failed = any(r.status == "failed" for r in results)
    sys.exit(1 if (failed or not verify_ok) else 0)


if __name__ == "__main__":
    main()
