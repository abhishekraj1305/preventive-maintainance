from datetime import date

import pytest
from maintenance.scheduling import due_date


@pytest.mark.parametrize(
    "anchor,count,unit,index,expected",
    [
        (date(2026, 1, 31), 1, "months", 1, date(2026, 2, 28)),
        (date(2026, 1, 31), 1, "months", 2, date(2026, 3, 31)),
        (date(2024, 1, 31), 1, "months", 1, date(2024, 2, 29)),
        (date(2026, 10, 31), 2, "weeks", 1, date(2026, 11, 14)),
        (date(2026, 10, 31), 10, "days", 2, date(2026, 11, 20)),
    ],
)
def test_recurring_dates_preserve_original_anchor(anchor, count, unit, index, expected):
    assert due_date(anchor, count, unit, index) == expected


def test_invalid_interval_rejected():
    with pytest.raises(ValueError):
        due_date(date(2026, 1, 1), 0, "days", 1)
