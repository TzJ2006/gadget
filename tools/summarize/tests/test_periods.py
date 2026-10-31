from datetime import date
import pytest
from summarize.periods import period_days, report_name
from summarize.public_api import report_name as public_report_name
from summarize.weekly_summary import _week_date_range


def test_iso_week_crosses_calendar_year_and_leap_month_has_29_days():
    days=period_days('week','2020-W53',strict=True)
    assert days[0]==date(2020,12,28) and days[-1]==date(2021,1,3)
    assert _week_date_range(2020,53)==(days[0],days[-1])
    assert len(period_days('month','2024-02',strict=True))==29
    assert len(period_days('month','2023-02',strict=True))==28
    assert public_report_name is report_name


@pytest.mark.parametrize('kind,label',[('week','2021-W53'),('week','../2026-W01'),('month','2026-13'),('month','2026-2')])
def test_public_labels_are_strict(kind,label):
    with pytest.raises(ValueError): period_days(kind,label,strict=True)


def test_legacy_month_adapter_keeps_its_non_padded_input_contract():
    assert period_days('month','2026-2')==period_days('month','2026-02')
