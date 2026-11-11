"""Keep every gadget test off the real host model-access ledger.

A test that fakes an unreachable Ollama host (test_engine_ollama) made model-access record an
"unknown" residency in the live ledger, which then refused every model load on this machine.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolated_model_access_ledger(monkeypatch, tmp_path):
    monkeypatch.setenv("PERSONALAGENT_RESOURCE_DIR", str(tmp_path / "model-resources"))
