"""Shared helpers and default paths for the daily summarize pipeline."""

import sys
from datetime import date
from typing import Optional

from common.paths import LOGS_DIR, REPORTS_DIR, CACHE_DIR

_DEFAULT_LOGS_DIR = LOGS_DIR / "summarize"
_DEFAULT_REPORTS_DIR = REPORTS_DIR / "summarize"
_DEFAULT_CACHE_DIR = CACHE_DIR / "summarize"


def _parse_date(date_str: Optional[str]) -> date:
    """解析日期字符串，None 时返回今天。"""
    if date_str:
        try:
            return date.fromisoformat(date_str)
        except ValueError:
            print(f"[error] 日期格式无效: {date_str}，请使用 YYYY-MM-DD")
            sys.exit(1)
    return date.today()
