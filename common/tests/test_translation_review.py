"""Local Qwen review of translated frontmatter — mocked, never hits Ollama."""

import json
import os

import pytest

from common.config import clear_cache
from common.llm import DEFAULT_OLLAMA_CHAT_MODEL
from common.translation import (
    DEFAULT_REVIEW_MODEL,
    resolve_review_model,
    resolve_review_tag,
    review_frontmatter_fields,
    review_is_enabled,
    translate_frontmatter,
)
from common.translation.frontmatter import (
    _build_review_prompt,
    _match_review_tag,
)
# Bound at import so the autouse _forbid_llm patch below can't shadow it.
from common.translation.frontmatter import _call_review_llm as _real_call_review_llm


FM = (
    "---\n"
    'title: "Yiran Chen — 研究者分析报告"\n'
    "date: 2026-03-16T22:00:00-05:00\n"
    "keywords:\n"
    "- 存内计算与神经形态加速器\n"
    "- Research\n"
    'summary: "他的学术轨迹呈现三段跃迁。"\n'
    "draft: false\n"
    "---\n"
)


class EchoEng:
    def generate_batch(self, prompts, **kw):
        return [p.split("\n\n", 1)[-1] for p in prompts]


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    monkeypatch.setenv("GADGET_CONFIG", str(tmp_path / "missing.json"))
    monkeypatch.delenv("GADGET_TRANSLATION_REVIEW_MODEL", raising=False)
    monkeypatch.delenv("GADGET_TRANSLATION_REVIEW", raising=False)
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    monkeypatch.setattr(
        "common.translation.frontmatter._ollama_tags", lambda *a, **k: None,
    )

    def _forbid_llm(*a, **k):
        raise AssertionError("review LLM must be mocked")

    monkeypatch.setattr(
        "common.translation.frontmatter._call_review_llm", _forbid_llm,
    )
    clear_cache()
    yield
    clear_cache()


def test_default_review_model_follows_chat_default():
    assert DEFAULT_REVIEW_MODEL == DEFAULT_OLLAMA_CHAT_MODEL == "gemma4:26b"
    assert resolve_review_model() == "gemma4:26b"


def test_review_model_follows_served_chat_tag(monkeypatch):
    """Review runs on the chat model, so an explicitly served tag wins over the
    bare default — else Ollama loads a second runner of the same ~18GB weights."""
    monkeypatch.setenv("OLLAMA_MODEL", "some-other-tag:latest")
    assert resolve_review_model() == "some-other-tag:latest"
    # config still outranks it
    monkeypatch.setenv("GADGET_TRANSLATION_REVIEW_MODEL", "other:tag")
    assert resolve_review_model() == "other:tag"


def test_review_model_env_overrides_config(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"translation": {"review_model": "qwen3.8:latest"}}), encoding="utf-8")
    monkeypatch.setenv("GADGET_CONFIG", str(cfg))
    clear_cache()
    assert resolve_review_model() == "qwen3.8:latest"
    monkeypatch.setenv("GADGET_TRANSLATION_REVIEW_MODEL", "qwen3.8:27b")
    assert resolve_review_model() == "qwen3.8:27b"


def test_review_disabled_by_env(monkeypatch, caplog):
    monkeypatch.setenv("GADGET_TRANSLATION_REVIEW", "0")
    assert review_is_enabled() is False
    with caplog.at_level("INFO"):
        assert resolve_review_tag() is None
    assert "disabled" in caplog.text


def test_review_skipped_when_ollama_down(monkeypatch, caplog):
    monkeypatch.setattr(
        "common.translation.frontmatter._ollama_tags", lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "common.translation.frontmatter._ollama_native_host",
        lambda: "http://127.0.0.1:11434",
    )
    with caplog.at_level("WARNING"):
        assert resolve_review_tag() is None
    assert "not reachable" in caplog.text


def test_review_skipped_when_model_not_pulled(monkeypatch, caplog):
    monkeypatch.setattr(
        "common.translation.frontmatter._ollama_tags",
        lambda *a, **k: ["llama3:latest"],
    )
    monkeypatch.setattr(
        "common.translation.frontmatter._ollama_native_host",
        lambda: "http://127.0.0.1:11434",
    )
    with caplog.at_level("WARNING"):
        assert resolve_review_tag() is None
    assert "not pulled" in caplog.text


def test_match_review_tag_accepts_bare_qwen38():
    assert _match_review_tag("qwen3.8", ["qwen3.8:27b"]) == "qwen3.8:27b"
    assert _match_review_tag("qwen3.8:latest", ["qwen3.8:latest"]) == "qwen3.8:latest"
    assert _match_review_tag("qwen3.8", ["llama3:latest"]) is None


def test_review_call_pins_model_and_disables_thinking(monkeypatch):
    """Without reasoning_effort=none, qwen3.x spends the whole 1024-token budget in
    <think> and returns empty content — the review then silently no-ops."""
    seen = {}
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "high")
    monkeypatch.setenv("OLLAMA_MODEL", "some-other-model")

    def fake_call(prompt, **kw):
        seen["model"] = os.environ.get("OLLAMA_MODEL")
        seen["effort"] = os.environ.get("OPENAI_REASONING_EFFORT")
        return '{"fields": []}'

    monkeypatch.setattr("common.llm.call_llm_raw", fake_call)
    # _real_call_review_llm, bound at import, bypasses the autouse _forbid_llm patch
    assert _real_call_review_llm("p", "qwen3.8:27b") == '{"fields": []}'
    assert seen == {"model": "qwen3.8:27b", "effort": "none"}
    # ambient env restored, not clobbered
    assert os.environ["OPENAI_REASONING_EFFORT"] == "high"
    assert os.environ["OLLAMA_MODEL"] == "some-other-model"


def test_review_skipped_when_llm_raises(monkeypatch, caplog):
    monkeypatch.setattr(
        "common.translation.frontmatter.resolve_review_tag", lambda: "qwen3.8:latest",
    )

    def boom(prompt, model):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("common.translation.frontmatter._call_review_llm", boom)
    with caplog.at_level("WARNING"):
        out = review_frontmatter_fields(["中文标题"], ["中文标题"], "en", prefixes=["title:"])
    assert out == ["中文标题"]
    assert "call failed" in caplog.text


def test_review_applies_json_corrections(monkeypatch):
    monkeypatch.setattr(
        "common.translation.frontmatter.resolve_review_tag", lambda: "qwen3.8:latest",
    )
    monkeypatch.setattr(
        "common.translation.frontmatter._call_review_llm",
        lambda prompt, model: json.dumps({
            "fields": [{"index": 0, "value": "Researcher Analysis Report"}],
        }),
    )
    out = translate_frontmatter(FM, "en", EchoEng())
    assert 'title: "Researcher Analysis Report"' in out
    assert "- Research" in out  # already English, index not in review payload


def test_review_keeps_english_proper_noun_on_zh(monkeypatch):
    monkeypatch.setattr(
        "common.translation.frontmatter.resolve_review_tag", lambda: "qwen3.8:latest",
    )

    def fake_llm(prompt, model):
        assert "保留英文" in prompt
        assert "该翻译的要翻译" in prompt
        return json.dumps({"fields": [{"index": 0, "value": "LeRobot"}]})

    monkeypatch.setattr("common.translation.frontmatter._call_review_llm", fake_llm)
    fm = '---\nsummary: "LeRobot"\n---\n'
    out = translate_frontmatter(fm, "zh", EchoEng())
    assert 'summary: "LeRobot"' in out


def test_review_prompt_states_policy():
    prompt = _build_review_prompt(
        ["Bug Journal"], ["缺陷日志"], "zh", ["title:"],
    )
    assert "该翻译的要翻译" in prompt
    assert "保留英文" in prompt
    assert "不要强行意译" in prompt


def test_english_gate_keeps_original_if_review_still_chinese(monkeypatch):
    monkeypatch.setattr(
        "common.translation.frontmatter.resolve_review_tag", lambda: "qwen3.8:latest",
    )
    monkeypatch.setattr(
        "common.translation.frontmatter._call_review_llm",
        lambda prompt, model: json.dumps({
            "fields": [{"index": 0, "value": "还是中文标题"}],
        }),
    )
    out = translate_frontmatter(FM, "en", EchoEng())
    # HY-MT echoed Chinese, review stayed Chinese → keep original title
    assert "Yiran Chen — 研究者分析报告" in out
