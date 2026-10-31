from datetime import timedelta
from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from maintenance.models import Breakdown, PMOccurrence
from maintenance.services import save_breakdown, record_fields
from maintenance.reporting import build_report
from maintenance.excel import preview_import, export_report
from .test_excel import workbook, row


def test_unreasonably_old_pm_import_is_rejected_before_reconciliation(factory):
    data = row(factory)
    data[5] = data[7] = "0001-01-01"
    data[9] = "days"
    result = preview_import(factory.admin, workbook([data]))
    assert result["errors"]


def test_admin_closing_breakdown_requires_and_records_plant_technician(factory):
    now = timezone.now()
    b = save_breakdown(
        factory.operator, {"machine": factory.machine, "occurred_at": now - timedelta(hours=3), "description": "Fault"}
    )
    data = {
        "repair_start": now - timedelta(hours=2),
        "repair_end": now - timedelta(hours=1),
        "root_cause": "Seal",
        "action_taken": "Replaced",
    }
    with pytest.raises(ValidationError):
        save_breakdown(factory.admin, data, b.pk, 1)
    with pytest.raises(ValidationError):
        save_breakdown(factory.admin, {**data, "technician": factory.outsider}, b.pk, 1)
    fixed = save_breakdown(factory.admin, {**data, "technician": factory.tech}, b.pk, 1)
    assert fixed.technician == factory.tech
    assert fixed.status == "closed"


def test_completed_historical_incident_can_precede_newer_incident(factory):
    now = timezone.now()
    save_breakdown(
        factory.operator,
        {"machine": factory.machine, "occurred_at": now - timedelta(hours=1), "description": "Current fault"},
    )
    historic = save_breakdown(
        factory.tech,
        {
            "machine": factory.machine,
            "occurred_at": now - timedelta(days=3),
            "description": "Earlier fault",
            "repair_start": now - timedelta(days=3) + timedelta(hours=1),
            "repair_end": now - timedelta(days=3) + timedelta(hours=2),
            "root_cause": "Bearing",
            "action_taken": "Replaced",
        },
    )
    assert historic.status == "closed"
    assert Breakdown.objects.count() == 2


def test_report_group_ids_not_display_names(factory):
    factory.other_plant.name = factory.plant.name
    factory.other_plant.save()
    result = build_report(factory.admin, timezone.localdate(), timezone.localdate())
    assert len(result["plant_rows"]) == 2
    assert len(result["department_rows"]) == 2


def test_export_contains_pm_history_completion_in_ist(factory):
    from openpyxl import load_workbook

    now = timezone.now()
    PMOccurrence.objects.create(
        **record_fields(factory.machine),
        plan=factory.plan,
        task_name="Check",
        due=timezone.localdate(),
        technician=factory.tech,
        approver=factory.approver,
        status="approved",
        completed_at=now,
    )
    report = build_report(factory.tech, timezone.localdate(), timezone.localdate())
    wb = load_workbook(BytesIO(export_report(report)))
    assert wb["PM tasks"].max_row == 2
    assert wb["PM tasks"]["E2"].value.hour == timezone.localtime(now).hour
