"""Public report-period rules. No model, history scan, sync or publish side effects."""
from datetime import date, datetime, timedelta
import calendar

def report_name(kind, label):
    """Validate the label before constructing a filename."""
    from datetime import datetime
    if kind == "day":
        return date.fromisoformat(label).isoformat() + ".json"
    if kind == "week":
        import re
        if not re.fullmatch(r"\d{4}-W\d{2}", label):
            raise ValueError("Expected YYYY-Www")
        date.fromisocalendar(int(label[:4]), int(label[-2:]), 1)
        return label + "-weekly.json"
    if kind == "month":
        if datetime.strptime(label, "%Y-%m").strftime("%Y-%m") != label:
            raise ValueError("Expected YYYY-MM")
        return label + "-monthly.json"
    raise ValueError("Unknown report kind")

def period_days(kind: str, value: str, *, strict: bool = False) -> list[date]:
    if strict:
        report_name(kind, value)
    if kind == "day":
        return [date.fromisoformat(value)]
    if kind == "week":
        year_text, week_text = value.split("-W", 1)
        monday = date.fromisocalendar(int(year_text), int(week_text), 1)
        return [monday + timedelta(days=offset) for offset in range(7)]
    if kind == "month":
        year_text, month_text = value.split("-", 1)
        year, month = int(year_text), int(month_text)
        if month < 1 or month > 12:
            raise ValueError(f"月份不可用: {value}")
        last = calendar.monthrange(year, month)[1]
        return [date(year, month, day) for day in range(1, last + 1)]
    raise ValueError(f"未知范围: {kind}")
