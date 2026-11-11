from common.translation.document import repair_markdown_boundaries


def test_glued_table_and_list_headers():
    source = "## 高被引论文| # | 标题 |\n|---|---|\n| 1 | Paper |\n\n## 研究方向- 机器人\n- 学习\n"
    fixed = repair_markdown_boundaries(source)
    assert "## 高被引论文\n\n| # | 标题 |" in fixed
    assert "## 研究方向\n\n- 机器人" in fixed
    assert repair_markdown_boundaries(fixed) == fixed


def test_leave_code_and_valid_heading_unchanged():
    source = "```md\n## heading| a | b |\n|---|---|\n```\n## A | B\nOrdinary text\n`## 研究方向- example`"
    assert repair_markdown_boundaries(source) == source


def test_header_row_and_separator_glued_together():
    source = "## Papers| # | Title|---|------|\n| 1 | Work |"
    assert repair_markdown_boundaries(source) == "## Papers\n\n| # | Title|\n|---|------|\n| 1 | Work |"
