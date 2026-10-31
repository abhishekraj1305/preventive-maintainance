from datetime import datetime, date, timedelta

import pytest
from django.utils import timezone
from maintenance.models import Breakdown, RuntimeLog, PMOccurrence
from maintenance.services import record_fields
from maintenance.reporting import build_report


def at(day, hour=0):
    return timezone.make_aware(datetime.combine(day, datetime.min.time())) + timedelta(hours=hour)


def test_cross_period_downtime_and_runtime_metrics(factory):
    day = date(2026, 10, 10)
    factory.machine.commissioned_on = date(2026, 1, 1)
    factory.machine.save()
    fields = record_fields(factory.machine)
    Breakdown.objects.create(
        **fields,
        occurred_at=at(day - timedelta(days=1), 23),
        repair_start=at(day),
        repair_end=at(day, 2),
        status="closed",
        reported_by=factory.operator,
        description="Overnight",
        technician=factory.tech,
    )
    Breakdown.objects.create(
        **fields,
        occurred_at=at(day, 6),
        repair_start=at(day, 7),
        repair_end=at(day, 8),
        status="closed",
        reported_by=factory.operator,
        description="Fault",
        technician=factory.tech,
    )
    RuntimeLog.objects.create(**fields, date=day, hours=8, entered_by=factory.operator)
    result = build_report(factory.tech, day, day)
    row = result["machine_rows"][0]
    assert result["breakdown_count"] == 1
    assert result["downtime_hours"] == pytest.approx(4)
    assert row["mttr"] == pytest.approx(1.5)
    assert row["mtbf"] == pytest.approx(8)
    assert result["machine_count"] == 1


def test_missing_runtime_and_no_failures_not_zero_mtbf(factory):
    day = timezone.localdate() - timedelta(days=1)
    result = build_report(factory.tech, day, day)
    assert result["machine_rows"][0]["mtbf"] is None
    assert result["machine_rows"][0]["runtime_complete"] is False
    RuntimeLog.objects.create(**record_fields(factory.machine), date=day, hours=0, entered_by=factory.operator)
    result = build_report(factory.tech, day, day)
    assert result["machine_rows"][0]["runtime_complete"] is True
    assert result["machine_rows"][0]["mtbf"] is None
    assert result["compliance"] is None


def test_compliance_counts_occurrences_and_requires_approved_on_time(factory):
    day = timezone.localdate() - timedelta(days=3)
    for index, status in enumerate(["approved", "approved", "submitted"]):
        due = day + timedelta(days=index)
        PMOccurrence.objects.create(
            **record_fields(factory.machine),
            plan=factory.plan,
            task_name="Task",
            technician=factory.tech,
            approver=factory.approver,
            due=due,
            status=status,
            completed_at=at(due, 12 if index == 0 else 25),
        )
    result = build_report(factory.tech, day, day + timedelta(days=2))
    assert result["pm_due"] == 3
    assert result["pm_completed"] == 2
    assert result["compliance"] == pytest.approx(100 / 3)
    assert result["pm_machine_count"] == 1


def test_report_filters_do_not_escape_plant_scope(factory):
    result = build_report(factory.tech, timezone.localdate(), timezone.localdate(), plant=factory.other_plant.pk)
    assert result["machine_count"] == 0
    assert result["machine_rows"] == []
