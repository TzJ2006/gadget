"""Readiness checks and guided onboarding for ``python -m summarize auto``.

The checks in this module are intentionally shallow: they verify local
configuration, executables, Python packages, and environment variables without
contacting remotes or making LLM calls.
"""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Optional, TextIO

from .config import _CONFIG_PATH, _load_config
from .remote import _find_rclone
from .usage import _ccusage_version


@dataclass(frozen=True)
class RequirementResult:
    """One summarize auto readiness check."""

    key: str
    label: str
    status: str
    required: bool
    detail: str
    action: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def default_hugo_site() -> Path:
    """Return the default Hugo site used by summarize deploy commands."""
    return Path(__file__).resolve().parent.parent / "website"


def _ok(key: str, label: str, detail: str, *, required: bool = True) -> RequirementResult:
    return RequirementResult(key, label, "ok", required, detail)


def _fail(key: str, label: str, detail: str, action: str) -> RequirementResult:
    return RequirementResult(key, label, "fail", True, detail, action)


def _warn(key: str, label: str, detail: str, action: str = "") -> RequirementResult:
    return RequirementResult(key, label, "warn", False, detail, action)


def _check_config_file() -> RequirementResult:
    if _CONFIG_PATH.exists():
        return _ok(
            "config-file",
            "summarize config",
            f"Found {_CONFIG_PATH}",
            required=False,
        )
    return _warn(
        "config-file",
        "summarize config",
        f"{_CONFIG_PATH} does not exist; defaults will be used.",
        "Run: python -m summarize onboard --init-config",
    )


def _check_rclone_remote(cfg: dict) -> RequirementResult:
    remote = cfg.get("rclone_remote")
    if not remote:
        return _fail(
            "rclone-remote",
            "rclone remote",
            "summarize auto currently uses daily merge --sync-all, which needs "
            f"rclone_remote in the summarize config ({_CONFIG_PATH}).",
            "Run: python -m summarize onboard --init-config",
        )
    if ":" not in remote:
        return _fail(
            "rclone-remote",
            "rclone remote",
            f"Configured rclone_remote does not look like '<remote>:<path>': {remote}",
            "Run: python -m summarize onboard --init-config",
        )
    return _ok("rclone-remote", "rclone remote", f"Configured: {remote}")


def _check_rclone_binary(cfg: dict) -> RequirementResult:
    if not cfg.get("rclone_remote"):
        return _warn(
            "rclone-binary",
            "rclone binary",
            "Skipped because rclone_remote is not configured.",
        )

    rclone_bin = _find_rclone()
    if rclone_bin:
        return _ok("rclone-binary", "rclone binary", f"Found {rclone_bin}")

    return _fail(
        "rclone-binary",
        "rclone binary",
        "rclone was not found in PATH or config rclone_path.",
        "Install rclone, or set rclone_path via: python -m summarize onboard --init-config",
    )


def _check_backend(api: str) -> list[RequirementResult]:
    if api == "claude_cli":
        claude = shutil.which("claude")
        if claude:
            return [_ok("llm-claude-cli", "Claude CLI", f"Found {claude}")]
        return [_fail(
            "llm-claude-cli",
            "Claude CLI",
            "The default --api claude_cli requires the claude executable.",
            "Install Claude Code CLI: npm install -g @anthropic-ai/claude-code",
        )]

    if api == "anthropic":
        results = []
        if importlib.util.find_spec("anthropic") is None:
            results.append(_fail(
                "llm-anthropic-package",
                "Anthropic package",
                "Python package 'anthropic' is not importable.",
                "Install summarize extras or run: pip install anthropic",
            ))
        else:
            results.append(_ok(
                "llm-anthropic-package",
                "Anthropic package",
                "Python package 'anthropic' is importable.",
            ))

        if os.environ.get("ANTHROPIC_API_KEY"):
            results.append(_ok(
                "llm-anthropic-key",
                "ANTHROPIC_API_KEY",
                "Environment variable is set.",
            ))
        else:
            results.append(_fail(
                "llm-anthropic-key",
                "ANTHROPIC_API_KEY",
                "Environment variable is not set.",
                "Set ANTHROPIC_API_KEY before running summarize auto.",
            ))
        return results

    if api == "openai":
        results = []
        if importlib.util.find_spec("openai") is None:
            results.append(_fail(
                "llm-openai-package",
                "OpenAI package",
                "Python package 'openai' is not importable.",
                "Install summarize extras or run: pip install openai",
            ))
        else:
            results.append(_ok(
                "llm-openai-package",
                "OpenAI package",
                "Python package 'openai' is importable.",
            ))

        if os.environ.get("OPENAI_API_KEY"):
            results.append(_ok(
                "llm-openai-key",
                "OPENAI_API_KEY",
                "Environment variable is set.",
            ))
        elif os.environ.get("OPENAI_BASE_URL"):
            results.append(_ok(
                "llm-openai-key",
                "OPENAI_API_KEY",
                "Not set, but OPENAI_BASE_URL points at a local server (keyless OK).",
            ))
        else:
            results.append(_fail(
                "llm-openai-key",
                "OPENAI_API_KEY",
                "Environment variable is not set.",
                "Set OPENAI_API_KEY, or set OPENAI_BASE_URL to a local vLLM/Ollama endpoint.",
            ))
        return results

    if api == "ollama":
        results = []
        if importlib.util.find_spec("openai") is None:
            results.append(_fail(
                "llm-openai-package",
                "OpenAI package",
                "Python package 'openai' is not importable (Ollama speaks the OpenAI protocol).",
                "Install summarize extras or run: pip install openai",
            ))
        else:
            results.append(_ok(
                "llm-openai-package",
                "OpenAI package",
                "Python package 'openai' is importable.",
            ))
        base = (os.environ.get("OLLAMA_BASE_URL")
                or os.environ.get("OPENAI_BASE_URL")
                or "http://127.0.0.1:11434/v1")
        results.append(_ok(
            "llm-ollama-endpoint",
            "Ollama endpoint",
            f"Keyless local server at {base} (override with OLLAMA_BASE_URL / OLLAMA_MODEL).",
        ))
        return results

    return [_fail(
        "llm-api",
        "LLM backend",
        f"Unsupported API backend: {api}",
        "Use one of: claude_cli, anthropic, openai, ollama.",
    )]


def _check_ccusage() -> RequirementResult:
    version = _ccusage_version()
    if version and version[0] >= 20:
        dotted = ".".join(str(part) for part in version)
        return _ok(
            "ccusage",
            "ccusage token stats",
            f"Found ccusage {dotted}.",
            required=False,
        )

    if shutil.which("npx") or shutil.which("npm"):
        return _warn(
            "ccusage",
            "ccusage token stats",
            "A global ccusage >=20 was not found; summarize can fall back to "
            "npx/npm, but token stats may be slower or unavailable offline.",
            "Optional: npm install -g ccusage@latest",
        )

    return _warn(
        "ccusage",
        "ccusage token stats",
        "ccusage and npm/npx were not found. Reports can still be generated, "
        "but token usage may be missing.",
        "Optional: install Node.js and ccusage@latest.",
    )


def _check_hugo_deploy(hugo_site: Optional[str | Path]) -> list[RequirementResult]:
    site = Path(hugo_site).expanduser() if hugo_site else default_hugo_site()
    results: list[RequirementResult] = []

    if site.is_dir():
        results.append(_ok("hugo-site", "Hugo site", f"Found {site}"))
    else:
        results.append(_fail(
            "hugo-site",
            "Hugo site",
            f"Hugo site directory does not exist: {site}",
            "Pass --hugo-site /path/to/site or create/configure the site.",
        ))
        return results

    sh_script = site / "update.sh"
    ps_script = site / "update.ps1"
    if sh_script.exists() or ps_script.exists():
        found = sh_script if sh_script.exists() else ps_script
        results.append(_ok("hugo-update-script", "Hugo update script", f"Found {found}"))
    else:
        results.append(_fail(
            "hugo-update-script",
            "Hugo update script",
            f"No update.sh or update.ps1 found in {site}",
            "Add an update script or run auto without --deploy.",
        ))

    hugo = shutil.which("hugo")
    if hugo:
        results.append(_ok("hugo-binary", "Hugo binary", f"Found {hugo}"))
    else:
        results.append(_fail(
            "hugo-binary",
            "Hugo binary",
            "The deploy update script calls the hugo executable.",
            "Install Hugo or run auto without --deploy.",
        ))

    if platform.system() != "Windows" and sh_script.exists() and not shutil.which("bash"):
        results.append(_fail(
            "bash",
            "bash",
            "update.sh exists but bash was not found.",
            "Install bash or use a platform-appropriate update script.",
        ))

    return results


def check_auto_requirements(
    *,
    api: str = "claude_cli",
    deploy: bool = False,
    hugo_site: Optional[str | Path] = None,
) -> list[RequirementResult]:
    """Return readiness results for the summarize auto workflow."""
    cfg = _load_config()
    results = [
        _check_config_file(),
        _check_rclone_remote(cfg),
        _check_rclone_binary(cfg),
        *_check_backend(api),
        _check_ccusage(),
    ]
    if deploy:
        results.extend(_check_hugo_deploy(hugo_site))
    return results


def has_blocking_failures(results: Iterable[RequirementResult]) -> bool:
    """Return True when any required readiness check failed."""
    return any(result.required and result.status == "fail" for result in results)


def _status_label(result: RequirementResult) -> str:
    if result.status == "ok":
        return "OK"
    if result.status == "warn":
        return "WARN"
    return "FAIL"


def print_report(
    results: Iterable[RequirementResult],
    *,
    include_ok: bool = True,
    stream: TextIO = sys.stdout,
) -> None:
    """Print a human-readable readiness report."""
    shown = [result for result in results if include_ok or not result.ok]
    if not shown:
        return

    print("[onboard] Requirement check:", file=stream)
    for result in shown:
        print(
            f"  [{_status_label(result)}] {result.label}: {result.detail}",
            file=stream,
        )
        if result.action and not result.ok:
            print(f"       Next: {result.action}", file=stream)


def _onboard_command(api: str, deploy: bool, hugo_site: Optional[str | Path]) -> str:
    parts = ["python", "-m", "summarize", "onboard", "--api", api]
    if deploy:
        parts.append("--deploy")
        if hugo_site:
            parts.extend(["--hugo-site", str(hugo_site)])
    return " ".join(parts)


def ensure_auto_ready(
    *,
    api: str = "claude_cli",
    deploy: bool = False,
    hugo_site: Optional[str | Path] = None,
    stream: TextIO = sys.stdout,
) -> bool:
    """Check auto readiness, print guidance, and return whether auto can run."""
    print("[onboard] Checking summarize auto requirements...", file=stream)
    results = check_auto_requirements(api=api, deploy=deploy, hugo_site=hugo_site)

    if has_blocking_failures(results):
        print_report(results, include_ok=False, stream=stream)
        print(
            f"[onboard] Blocking requirements are missing. Run: "
            f"{_onboard_command(api, deploy, hugo_site)}",
            file=stream,
        )
        return False

    warnings = [result for result in results if result.status == "warn"]
    if warnings:
        print_report(warnings, include_ok=False, stream=stream)
    print("[onboard] Required checks passed.", file=stream)
    return True


def cmd_onboard(args) -> None:
    """CLI handler for ``python -m summarize onboard``."""
    if getattr(args, "init_config", False):
        from . import config as config_mod
        from .daily import _config_init

        _config_init()
        # _config_init writes the repo-local config, but _CONFIG_PATH was resolved
        # at import time (before the file existed). Re-resolve it in both modules
        # so the readiness checks below see the config we just wrote.
        global _CONFIG_PATH
        _CONFIG_PATH = config_mod._CONFIG_PATH = config_mod._resolve_config_path()
        config_mod._cached_config = None

    results = check_auto_requirements(
        api=getattr(args, "api", "claude_cli"),
        deploy=getattr(args, "deploy", False),
        hugo_site=getattr(args, "hugo_site", None),
    )

    if getattr(args, "json", False):
        print(json.dumps([asdict(result) for result in results], indent=2))
    else:
        print_report(results)

    if has_blocking_failures(results):
        sys.exit(1)
