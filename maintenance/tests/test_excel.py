from io import BytesIO
import pytest
from openpyxl import Workbook, load_workbook
from django.core.exceptions import PermissionDenied, ValidationError
from maintenance.models import Machine
from maintenance.excel import IMPORT_HEADERS, preview_import, commit_import, export_report
from maintenance.reporting import build_report
from django.utils import timezone


def workbook(rows):
    wb = Workbook()
    wb.active.append(IMPORT_HEADERS)
    for row in rows:
        wb.active.append(row)
    out = BytesIO()
    wb.save(out)
    out.seek(0)
    return out


def row(factory, code="NEW-01"):
    return [
        "P1",
        "PRESS",
        code,
        "New press",
        100,
        "2026-01-01",
        "Weekly safety",
        "2026-11-15",
        1,
        "weeks",
        "tech",
        "approver",
    ]


def test_import_preview_and_commit_are_atomic(factory):
    good = row(factory)
    bad = row(factory, "BAD")
    bad[0] = "UNKNOWN"
    result = preview_import(factory.admin, workbook([good, bad]))
    assert result["errors"]
    assert not Machine.objects.filter(code="NEW-01").exists()
    with pytest.raises(ValidationError):
        commit_import(factory.admin, result)
    result = preview_import(factory.admin, workbook([good]))
    assert not result["errors"]
    counts = commit_import(factory.admin, result)
    assert counts == {"machines": 1, "plans": 1}
    with pytest.raises(ValidationError):
        commit_import(factory.admin, result)


def test_import_role_assignments_revalidated_at_commit(factory):
    result = preview_import(factory.admin, workbook([row(factory)]))
    factory.tech.memberships.all().delete()
    with pytest.raises(ValidationError):
        commit_import(factory.admin, result)
    assert not Machine.objects.filter(code="NEW-01").exists()


def test_nonadmin_cannot_import_and_formula_injection_is_escaped(factory):
    with pytest.raises(PermissionDenied):
        preview_import(factory.operator, workbook([row(factory)]))
    factory.machine.name = '=HYPERLINK("evil")'
    factory.machine.save()
    report = build_report(factory.admin, timezone.localdate(), timezone.localdate())
    wb = load_workbook(BytesIO(export_report(report)))
    assert all(cell.data_type != "f" for sheet in wb for cells in sheet for cell in cells)
