"""English pages must not carry Chinese frontmatter, and an echoing model must
not get its output stamped as a valid translation."""

import pytest

from common.translation import (
    _LABEL_LIST_KEYS,
    _scan_frontmatter_fields,
    build_translation_prompt,
    translate_frontmatter,
    translate_markdown_document,
    validate_translated_output,
    wrong_language,
)


@pytest.fixture(autouse=True)
def _skip_qwen_review(monkeypatch):
    """Existing tests mock only HY-MT. Skip Qwen review so a live Ollama
    cannot rewrite assertions or stall on /api/tags."""
    monkeypatch.setattr(
        "common.translation.frontmatter.resolve_review_tag", lambda: None,
    )

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


class Eng:
    def __init__(self):
        self.prompts = []

    def generate_batch(self, prompts, **kw):
        self.prompts = prompts
        return [f"T{i}" for i in range(len(prompts))]


def test_title_and_keywords_are_translatable():
    _, fields = _scan_frontmatter_fields(FM, include_labels=True)
    assert [f[0] for f in fields] == [1, 4, 5, 6]  # title, 2 keywords, summary


def test_labels_are_skipped_by_default():
    _, fields = _scan_frontmatter_fields(FM)
    assert [f[0] for f in fields] == [6]  # summary only


def test_non_list_scalars_are_left_alone():
    _, fields = _scan_frontmatter_fields("---\ndate: 2026-01-01\ndraft: false\n---\n")
    assert fields == []


def test_translate_frontmatter_rewrites_title_and_list_items():
    out = translate_frontmatter(FM, "en", Eng())
    assert 'title: "T0"' in out
    assert "- T1" in out and "- T2" in out
    assert 'summary: "T3"' in out
    assert "date: 2026-03-16T22:00:00-05:00" in out  # untouched


def test_shared_english_labels_survive_translation_into_chinese():
    """Titles and tags stay as-is on the Chinese side — "Bug Journal 2026-02-01"
    must not splinter into a different Chinese rendering on every page."""
    out = translate_frontmatter(FM, "zh", Eng())
    assert "- Research" in out and "- 存内计算与神经形态加速器" in out
    assert 'title: "Yiran Chen — 研究者分析报告"' in out
    assert 'summary: "T0"' in out  # prose still translated


@pytest.mark.parametrize("text,lang,expected", [
    ("这是一段足够长的中文正文，用来判断语言检测是否可靠工作。", "en", True),
    ("This is a long enough English body to judge the language reliably.", "en", False),
    ("```py\nprint('hi')\n```\n", "zh", False),   # all code → not enough prose to judge
    ("短", "en", False),                            # too short to judge
])
def test_wrong_language(text, lang, expected):
    assert wrong_language(text, lang) is expected


def test_echoed_translation_is_rejected():
    doc = "---\ntitle: t\n---\n\n" + "这是一段完全没有被翻译的中文正文内容。" * 3
    with pytest.raises(ValueError, match="not in en"):
        validate_translated_output(doc, doc, "en")
    assert validate_translated_output(doc, doc) == doc  # no target_lang → old behavior


def test_english_page_with_chinese_title_is_rejected():
    """Document-level 5% CJK misses a leaked Chinese title on a long English body."""
    body = "This is a long enough English body to judge the language reliably. " * 8
    doc = "---\ntitle: 研究者分析报告\n---\n\n" + body
    with pytest.raises(ValueError, match=r"Frontmatter field\(s\) not in en"):
        validate_translated_output(doc, doc, "en")


def test_english_title_survives_on_chinese_page():
    """Originally-English titles stay English on the Chinese side — not a mismatch."""
    body = "这是一段足够长的中文正文，用来判断语言检测是否可靠工作。" * 3
    doc = '---\ntitle: "Bug Journal"\nsummary: "他的学术轨迹呈现三段跃迁。"\n---\n\n' + body
    assert validate_translated_output(doc, doc, "zh") == doc


def test_english_proper_noun_summary_ok_on_chinese_page():
    """Field-level checks do not force-translate English proper nouns on zh pages."""
    body = "这是一段足够长的中文正文，用来判断语言检测是否可靠工作。" * 3
    doc = '---\ntitle: "LeRobot"\nsummary: "LeRobot"\n---\n\n' + body
    assert validate_translated_output(doc, doc, "zh") == doc


def test_label_list_keys_are_keywords_tags_categories():
    assert _LABEL_LIST_KEYS == ("keywords:", "tags:", "categories:")
    assert "_TRANSLATABLE_LIST_KEYS" not in (translate_frontmatter.__doc__ or "")


def test_zh_prompt_keeps_originally_english_titles():
    p = build_translation_prompt("hi", "zh", markdown=False)
    assert "该翻译的内容必须翻译" in p
    assert "保留英文" in p


def test_en_prompt_still_asks_to_translate():
    p = build_translation_prompt("hi", "en", markdown=False)
    assert "该翻译的内容必须翻译" in p
    assert "不要强行意译" not in p  # that clause is zh-UI only


class EchoEng:
    def generate_batch(self, prompts, **kw):
        return [p.split("\n\n", 1)[-1] for p in prompts]


def test_translate_markdown_rejects_chinese_title_on_english_page():
    body = "This English body is long enough to pass the document-level CJK check. " * 5
    doc = '---\ntitle: "研究者分析报告"\n---\n\n' + body
    with pytest.raises(ValueError, match=r"Frontmatter field\(s\) not in en"):
        translate_markdown_document(doc, "zh", "en", engine=EchoEng())


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
