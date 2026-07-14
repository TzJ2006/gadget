"""Persisted translator model list — built-in defaults + user-managed additions.

Stored in the ``translator.models`` key of the repo-root ``config.json``.
The UI (app.py) reads this for the model dropdown and edits it via add/remove.
"""

from __future__ import annotations

from common import config as gadget_config

# First entry is the GUI default. 7B / FP8 download + load on first selection.
DEFAULT_MODELS = [
    "tencent/Hy-MT2-1.8B",
    "tencent/Hy-MT2-1.8B-FP8",
    "tencent/Hy-MT2-7B",
    "tencent/Hy-MT2-7B-FP8",
]

# Back-compat alias: path of the unified root config (not a separate models file).
CONFIG_PATH = gadget_config.DEFAULT_CONFIG_PATH


def _read() -> list[str] | None:
    models = gadget_config.load_section("translator").get("models")
    return models if isinstance(models, list) and models else None


def load_models() -> list[str]:
    """Current model list: stored config if present, else the built-in defaults."""
    return _read() or list(DEFAULT_MODELS)


def _save(models: list[str]) -> None:
    gadget_config.update_section("translator", {"models": models}, replace=True)


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
    import os
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mkdtemp()) / "config.json"
    os.environ["GADGET_CONFIG"] = str(tmp)
    gadget_config.clear_cache()
    assert load_models() == DEFAULT_MODELS, "fresh load must return defaults"
    assert add_model("foo/bar")[-1] == "foo/bar", "add appends"
    assert add_model("foo/bar").count("foo/bar") == 1, "add dedupes"
    assert load_models()[-1] == "foo/bar", "add persists"
    assert "foo/bar" not in remove_model("foo/bar"), "remove drops it"
    assert remove_model("nope") == load_models(), "removing absent id is a no-op"
    # emptying everything falls back to defaults rather than an unusable empty list
    for m in list(load_models()):
        remove_model(m)
    assert load_models() == DEFAULT_MODELS, "empty falls back to defaults"
    print("models.py self-check OK")
