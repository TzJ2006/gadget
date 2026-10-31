"""Run settings for zhbench.py, enbench.py, and docbench.py.

Reads config.json in this directory, or config.example.json when that local
file is absent. CLI flags override the file. The model roster lives in the
config, not in the runners.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SUITES = ("zh", "en", "doc")
EXAMPLE_NAME = "config.example.json"
LOCAL_NAME = "config.json"

# Full paths: CreateProcess does not resolve extensionless npm shims.
CURSOR = r"C:\Users\tongt\AppData\Local\cursor-agent\cursor-agent.cmd"
NPM = r"C:\Users\tongt\AppData\Roaming\npm"
CODEX_EXE = NPM + r"\codex.cmd"
CLI_BIN = {"codex": CODEX_EXE, "claude": "claude", "cursor": CURSOR}

# No --bare on claude: it drops the OAuth settings source and the run 401s.
_CODEX_PREFIX = [
    CODEX_EXE, "exec", "--json", "--sandbox", "read-only",
    "--skip-git-repo-check", "-c", 'model_reasoning_effort="medium"',
]
_CLAUDE_TAIL = [
    "--output-format", "json",
    "--disallowed-tools", "Bash,Edit,Write,Read,Glob,Grep",
]
_CURSOR_PREFIX = [
    CURSOR, "--print", "--output-format", "json", "--mode", "ask", "--trust",
]


def repo_root() -> Path:
    """Directory that contains both outputs/ and tools/, from this file upward."""
    for p in (HERE, *HERE.parents):
        if (p / "outputs").is_dir() and (p / "tools").is_dir():
            return p
    raise SystemExit("cannot find repo root (directory containing outputs/ and tools/)")


def config_path() -> Path:
    local = HERE / LOCAL_NAME
    example = HERE / EXAMPLE_NAME
    if local.is_file():
        return local
    if example.is_file():
        return example
    raise SystemExit(f"missing {local} and {example}")


def load_config() -> dict:
    path = config_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{path}: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit(f"{path}: config must be a JSON object")
    data["_source"] = str(path)
    return data


def suite_names(cfg: dict) -> list:
    raw = cfg.get("suites", list(SUITES))
    if raw is None:
        return list(SUITES)
    if not isinstance(raw, list):
        raise SystemExit("suites must be a list of zh, en, doc")
    bad = [name for name in raw if name not in SUITES]
    if bad:
        raise SystemExit(f"unknown suites {bad}; expected zh, en, doc")
    return list(raw)


def output_dir(cfg: dict) -> Path:
    raw = cfg.get("output_dir") or "outputs/reports"
    path = Path(str(raw))
    if not path.is_absolute():
        path = repo_root() / path
    return path


def _enabled(entry: dict) -> bool:
    return entry.get("enabled", True) is not False


def ollama_models(cfg: dict) -> list:
    raw = cfg.get("models", {}).get("ollama", [])
    if not isinstance(raw, list):
        raise SystemExit("models.ollama must be a list")
    names = []
    for item in raw:
        if isinstance(item, str):
            names.append(item)
            continue
        if not isinstance(item, dict):
            raise SystemExit(f"ollama entry must be a string or object, got {item!r}")
        if not _enabled(item):
            continue
        name = item.get("model")
        if not isinstance(name, str) or not name:
            raise SystemExit(f"ollama entry missing model: {item}")
        names.append(name)
    return names


def _cli_entry(backend: str, item) -> dict:
    if not isinstance(item, dict):
        raise SystemExit(f"models.{backend} entries must be objects with key and model")
    key = item.get("key")
    model = item.get("model")
    if not isinstance(key, str) or not key:
        raise SystemExit(f"models.{backend} entry missing key: {item}")
    if not isinstance(model, str) or not model:
        raise SystemExit(f"{key}: missing model")
    effort = item.get("effort")
    if effort is not None and backend != "claude":
        raise SystemExit(f"{key}: effort is only supported for claude")
    if effort is not None and not isinstance(effort, str):
        raise SystemExit(f"{key}: effort must be a string")
    return {"key": key, "model": model, "effort": effort or None, "enabled": _enabled(item)}


def cli_entries(cfg: dict) -> list:
    models = cfg.get("models", {})
    if not isinstance(models, dict):
        raise SystemExit("models must be an object")
    entries = []
    seen = set()
    dupes = []
    for backend in ("codex", "claude", "cursor"):
        raw = models.get(backend, [])
        if not isinstance(raw, list):
            raise SystemExit(f"models.{backend} must be a list")
        for item in raw:
            parsed = _cli_entry(backend, item)
            if parsed["key"] in seen:
                dupes.append(parsed["key"])
            seen.add(parsed["key"])
            if parsed["enabled"]:
                parsed["backend"] = backend
                entries.append(parsed)
    if dupes:
        raise SystemExit(f"duplicate model keys: {sorted(set(dupes))}")
    return entries


def cli_jobs(cfg: dict, prompt_mode: str, prompt: str) -> list:
    """Return (key, argv) pairs.

    prompt_mode "argv" puts the prompt on the command line (zhbench, enbench).
    prompt_mode "stdin" leaves the prompt to the caller; codex still receives
    "-" so it reads stdin (docbench).
    """
    if prompt_mode not in ("argv", "stdin"):
        raise SystemExit(f"bad prompt_mode {prompt_mode!r}")
    jobs = []
    for entry in cli_entries(cfg):
        backend = entry["backend"]
        model = entry["model"]
        if backend == "codex":
            argv = _CODEX_PREFIX + ["-m", model]
            argv.append(prompt if prompt_mode == "argv" else "-")
        elif backend == "claude":
            argv = ["claude", "-p"]
            if prompt_mode == "argv":
                argv.append(prompt)
            argv += _CLAUDE_TAIL + ["--model", model]
            if entry["effort"]:
                argv += ["--effort", entry["effort"]]
        else:
            argv = _CURSOR_PREFIX + ["--model", model]
            if prompt_mode == "argv":
                argv.append(prompt)
        jobs.append((entry["key"], argv))
    return jobs


def _last_bool(argv: list, on: str, off: str, default: bool) -> bool:
    chosen = None
    for arg in argv:
        if arg == on:
            chosen = True
        elif arg == off:
            chosen = False
    return default if chosen is None else chosen


def filters(cfg: dict, argv=None) -> tuple:
    """only, skip_cli, skip_ollama. Flags override the config file."""
    argv = list(sys.argv if argv is None else argv)
    only = cfg.get("only") or None
    if isinstance(only, str) and not only.strip():
        only = None
    if "--only" in argv:
        index = argv.index("--only")
        if index + 1 >= len(argv) or str(argv[index + 1]).startswith("--"):
            raise SystemExit("--only needs a model substring")
        only = argv[index + 1]
    skip_cli = _last_bool(argv, "--skip-cli", "--no-skip-cli", bool(cfg.get("skip_cli", False)))
    skip_ollama = _last_bool(
        argv, "--skip-ollama", "--no-skip-ollama", bool(cfg.get("skip_ollama", False)))
    return only, skip_cli, skip_ollama


def publish_enabled(cfg: dict, argv=None) -> bool:
    """Whether run.py pushes the Hugo site after writing posts.

    Defaults to on. ``publish: false`` or ``--no-publish`` turns it off;
    ``--publish`` turns it back on. The last of those two flags wins.
    Article generation is not gated by this switch.
    """
    argv = list(sys.argv if argv is None else argv)
    raw = cfg.get("publish", True)
    if raw is None:
        raw = True
    return _last_bool(argv, "--publish", "--no-publish", bool(raw))


def prepare_run(suite: str, argv=None) -> dict:
    if suite not in SUITES:
        raise SystemExit(f"unknown suite {suite}")
    cfg = load_config()
    only, skip_cli, skip_ollama = filters(cfg, argv)
    return {
        "enabled": suite in suite_names(cfg),
        "source": cfg["_source"],
        "out_dir": output_dir(cfg),
        "only": only,
        "skip_cli": skip_cli,
        "skip_ollama": skip_ollama,
        "ollama": ollama_models(cfg),
        "config": cfg,
    }
