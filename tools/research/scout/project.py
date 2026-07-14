"""Project CRUD operations for Research Scout."""

from __future__ import annotations

import json
import logging
import re
import shutil
import sys
from datetime import date
from pathlib import Path

from common.io import atomic_write
from common.json_utils import try_repair_result as _try_repair_result

from scout.config import PROJECTS_DIR, get_logger

logger = get_logger()

# ─── Project schema and overview template ────────────────────────────

PROJECT_JSON_SCHEMA = {
    "id": "",
    "title": "",
    "status": "active",
    "search_keywords": [],
    "arxiv_categories": [],
    "arxiv_query_override": None,
    "last_searched": None,
    "open_questions": [],
    "created": "",
    "notes": "",
    "lookback_days": None,
    "max_results": None,
    "sources": ["arxiv"],
    "pubmed_journals": [],
    "biorxiv_categories": [],
}

OVERVIEW_TEMPLATE = """# {title}

## Positioning
> One sentence describing what this project does and what gap it fills

## Core Problems
- Problem 1
- Problem 2

## Current Methods & Progress
- Method description
- Key milestones

## Open Questions & New Ideas
{open_questions_list}

## Related Keywords
{keywords_list}

## Literature Notes
<!-- research_scout auto-append below -->
"""


def create_project(project_id: str, title: str,
                   keywords: list[str], categories: list[str],
                   open_questions: list[str] | None = None) -> Path:
    """Create a new project directory with project.json and overview.md."""
    project_dir = PROJECTS_DIR / project_id
    if project_dir.exists():
        logger.error("项目目录已存在: %s", project_dir)
        sys.exit(1)

    project_dir.mkdir(parents=True, exist_ok=True)

    # project.json
    pj = dict(PROJECT_JSON_SCHEMA)
    pj["id"] = project_id
    pj["title"] = title
    pj["search_keywords"] = keywords
    pj["arxiv_categories"] = categories
    pj["open_questions"] = open_questions or []
    pj["created"] = date.today().isoformat()

    atomic_write(project_dir / "project.json",
                 json.dumps(pj, ensure_ascii=False, indent=2))

    # overview.md
    oq_list = "\n".join(f"- [ ] {q}" for q in (open_questions or [])) or "- [ ] (to be added)"
    kw_list = ", ".join(keywords) if keywords else "(to be added)"
    overview = OVERVIEW_TEMPLATE.format(
        title=title,
        open_questions_list=oq_list,
        keywords_list=kw_list,
    )
    atomic_write(project_dir / "overview.md", overview)

    logger.info("项目已创建: %s", project_dir)
    logger.info("  project.json: %s", project_dir / "project.json")
    logger.info("  overview.md:  %s", project_dir / "overview.md")
    return project_dir


def create_project_from_query(plan: dict) -> tuple[dict, Path]:
    """Create a project from a validated ask plan (natural language query).

    Generates a timestamp-based unique project ID, sets status='ask',
    and populates overview.md with the LLM-generated summary.

    Returns (project_dict, project_dir).
    """
    from datetime import datetime

    # Generate collision-safe ID: ask-YYYYMMDD-HHMMSS-ffffff
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    project_id = f"ask-{timestamp}"

    title = plan.get("title", "Untitled Ask Query")
    keywords = plan.get("search_keywords", [])
    categories = plan.get("arxiv_categories", [])
    questions = plan.get("open_questions", [])

    project_dir = PROJECTS_DIR / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    # Build project.json with ask-specific fields
    pj = dict(PROJECT_JSON_SCHEMA)
    pj["id"] = project_id
    pj["title"] = title
    pj["status"] = "ask"
    pj["search_keywords"] = keywords
    pj["arxiv_categories"] = categories
    pj["open_questions"] = questions
    pj["created"] = date.today().isoformat()
    pj["sources"] = plan.get("sources", ["arxiv"])
    pj["pubmed_journals"] = plan.get("pubmed_journals", [])
    pj["biorxiv_categories"] = plan.get("biorxiv_categories", [])
    pj["lookback_days"] = plan.get("lookback_days")

    atomic_write(project_dir / "project.json",
                 json.dumps(pj, ensure_ascii=False, indent=2))

    # Build overview.md — use LLM summary instead of placeholder
    summary = plan.get("overview_summary", "").strip()
    current_methods = summary if summary else "- (auto-created by ask command, no detailed description yet)"

    oq_list = "\n".join(f"- [ ] {q}" for q in questions) or "- [ ] (to be added)"
    kw_list = ", ".join(keywords) if keywords else "(to be added)"

    overview = OVERVIEW_TEMPLATE.format(
        title=title,
        open_questions_list=oq_list,
        keywords_list=kw_list,
    )
    # Replace placeholder "Current Methods & Progress" section with actual summary
    overview = overview.replace(
        "- Method description\n- Key milestones",
        current_methods,
    )

    atomic_write(project_dir / "overview.md", overview)

    logger.info("ask 项目已创建: %s (%s)", project_id, title)
    return pj, project_dir


def create_project_from_overview(project_id: str, overview_path: str,
                                 api: str = "claude_cli",
                                 timeout: int = 600) -> Path:
    """Create project from existing overview.md (LLM extracts title/keywords/questions)."""
    # Lazy import to avoid circular dependency
    from scout.evaluate import call_scout_llm
    from scout.prompts import OVERVIEW_EXTRACT_PROMPT

    overview_file = Path(overview_path)
    if not overview_file.exists():
        logger.error("overview 文件不存在: %s", overview_path)
        sys.exit(1)

    content = overview_file.read_text(encoding="utf-8")
    if not content.strip():
        logger.error("overview 文件为空: %s", overview_path)
        sys.exit(1)

    prompt = OVERVIEW_EXTRACT_PROMPT.format(overview_content=content)
    logger.info("从 overview.md 提取项目信息 (api=%s)...", api)
    result = call_scout_llm(api, prompt, timeout)
    result = _try_repair_result(result, api, timeout)

    title = result.get("title", project_id)
    keywords = result.get("search_keywords", [])
    categories = result.get("arxiv_categories", [])
    questions = result.get("open_questions", [])

    logger.info("LLM 提取结果:")
    logger.info("  title: %s", title)
    logger.info("  keywords: %s", keywords)
    logger.info("  categories: %s", categories)
    logger.info("  questions: %s", questions)

    project_dir = create_project(project_id, title, keywords, categories, questions)

    # Override template with original overview.md
    shutil.copy2(overview_file, project_dir / "overview.md")
    logger.info("已将原始 overview.md 复制到项目目录")

    return project_dir


def load_project(project_id: str) -> dict:
    """Load a single project's project.json."""
    pj_path = PROJECTS_DIR / project_id / "project.json"
    if not pj_path.exists():
        logger.error("项目不存在: %s (%s)", project_id, pj_path)
        sys.exit(1)

    with open(pj_path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_project(project: dict) -> None:
    """Save project.json (atomic write)."""
    project_id = project["id"]
    pj_path = PROJECTS_DIR / project_id / "project.json"
    atomic_write(pj_path, json.dumps(project, ensure_ascii=False, indent=2))


def load_all_projects(status_filter: str | None = None) -> list[dict]:
    """Scan projects/ directory for all project.json files, optionally filter by status."""
    projects = []
    if not PROJECTS_DIR.exists():
        return projects

    for d in sorted(PROJECTS_DIR.iterdir()):
        pj_path = d / "project.json"
        if not pj_path.is_file():
            continue
        try:
            with open(pj_path, "r", encoding="utf-8") as f:
                pj = json.load(f)
            if status_filter and pj.get("status") != status_filter:
                continue
            projects.append(pj)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("跳过无效项目 %s: %s", d.name, e)

    return projects


def extract_current_methods(project_id: str) -> str:
    """Extract 'Current Methods & Progress' section from overview.md."""
    overview_path = PROJECTS_DIR / project_id / "overview.md"
    if not overview_path.exists():
        return "(overview.md not found)"

    content = overview_path.read_text(encoding="utf-8")
    match = re.search(
        r"##\s*Current Methods & Progress\s*\n(.*?)(?=\n##|\Z)",
        content, re.DOTALL,
    )
    if match:
        text = match.group(1).strip()
        if text and text != "- Method description\n- Key milestones":
            return text
    return "(no records yet)"
