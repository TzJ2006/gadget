"""English pages must not carry Chinese frontmatter, and an echoing model must
not get its output stamped as a valid translation."""

import pytest

from common.translation import (
    _scan_frontmatter_fields,
    translate_frontmatter,
    validate_translated_output,
    wrong_language,
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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
