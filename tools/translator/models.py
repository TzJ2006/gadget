"""Persisted translator model list — built-in defaults + user-managed additions.

Stored at ``~/.config/gadget/translator_models.json`` as ``{"models": [...]}``.
The UI (app.py) reads this for the model dropdown and edits it via add/remove.
"""

from __future__ import annotations

import json
from pathlib import Path

from common.io import atomic_write

# First entry is the GUI default. 7B / FP8 download + load on first selection.
DEFAULT_MODELS = [
    "tencent/Hy-MT2-1.8B",
    "tencent/Hy-MT2-1.8B-FP8",
    "tencent/Hy-MT2-7B",
    "tencent/Hy-MT2-7B-FP8",
]

CONFIG_PATH = Path.home() / ".config" / "gadget" / "translator_models.json"


def _read() -> list[str] | None:
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    models = data.get("models") if isinstance(data, dict) else None
    return models if isinstance(models, list) and models else None


def load_models() -> list[str]:
    """Current model list: stored config if present, else the built-in defaults."""
    return _read() or list(DEFAULT_MODELS)


def _save(models: list[str]) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(CONFIG_PATH, json.dumps({"models": models}, ensure_ascii=False, indent=2))


def add_model(model_id: str) -> list[str]:
    """Add a HuggingFace model id (no-op if blank/duplicate). Returns the new list."""
    model_id = (model_id or "").strip()
    models = load_models()
    if model_id and model_id not in models:
        models.append(model_id)
        _save(models)
    return models


def remove_model(model_id: str) -> list[str]:
    """Remove a model id if present (keeps at least the defaults if list empties)."""
    models = [m for m in load_models() if m != model_id]
    _save(models or DEFAULT_MODELS)
    return models or list(DEFAULT_MODELS)


if __name__ == "__main__":  # self-check: add/remove/dedupe/persist round-trip
    import tempfile

    CONFIG_PATH = Path(tempfile.mkdtemp()) / "translator_models.json"
    assert load_models() == DEFAULT_MODELS, "fresh load must return defaults"
    assert add_model("foo/bar")[-1] == "foo/bar", "add appends"
    assert add_model("foo/bar").count("foo/bar") == 1, "add dedupes"
    assert load_models()[-1] == "foo/bar", "add persists"
    assert "foo/bar" not in remove_model("foo/bar"), "remove drops it"
    assert remove_model("nope") == load_models(), "removing absent id is a no-op"
    # emptying everything falls back to defaults rather than an unusable empty list
    for m in load_models():
        remove_model(m)
    assert load_models() == DEFAULT_MODELS, "empty falls back to defaults"
    print("models.py self-check OK")
