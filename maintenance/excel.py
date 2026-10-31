"""Small, bounded XLSX imports. Previews are stored server-side and revalidated."""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from zipfile import ZipFile, BadZipFile

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, IntegrityError
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill, Alignment

from .access import is_admin
from .models import Plant, Department, User, Membership, Machine, PMPlan
from .services import audit
from .validation import validate_commissioning, validate_schedule

IMPORT_HEADERS = [
    "plant_code",
    "department_code",
    "machine_id",
    "machine_name",
    "tonnage",
    "commissioned_on",
    "pm_name",
    "first_due",
    "interval",
    "unit",
    "technician_id",
    "approver_id",
]


def require_admin(user):
    if not is_admin(user):
        raise PermissionDenied("Only an administrator can import master records.")


def _date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip())


def _validate_rows(rows):
    errors, prepared, seen_plans, seen_machines = [], [], set(), {}
    for number, row in enumerate(rows, 2):
        try:
            if len(row) != len(IMPORT_HEADERS):
                raise ValueError("Expected the template columns, in the original order.")
            data = dict(zip(IMPORT_HEADERS, row))
            plant = Plant.objects.get(code=data["plant_code"], active=True)
            department = Department.objects.get(plant=plant, code=data["department_code"])
            code, name = str(data["machine_id"]).strip(), str(data["machine_name"]).strip()
            if not code or len(code) > 50 or not name or len(name) > 150:
                raise ValueError("Machine ID (1–50 characters) and name (1–150) are required.")
            tonnage = Decimal(str(data["tonnage"]))
            if not tonnage.is_finite() or not 0 <= tonnage < 100000000 or tonnage.as_tuple().exponent < -2:
                raise ValueError("Tonnage must be non-negative, with at most two decimal places.")
            commissioned = _date(data["commissioned_on"])
            validate_commissioning(commissioned)
            machine_key = (plant.pk, code)
            master = (department.pk, name, str(tonnage.normalize()), commissioned.isoformat())
            if machine_key in seen_machines and seen_machines[machine_key] != master:
                raise ValueError("Repeated machine rows have conflicting master details.")
            seen_machines[machine_key] = master
            existing = Machine.objects.filter(plant=plant, code=code).first()
            if (
                existing
                and (
                    existing.department_id,
                    existing.name,
                    str(existing.tonnage.normalize()),
                    existing.commissioned_on.isoformat(),
                )
                != master
            ):
                raise ValueError("Existing machine details differ. Update them in the app before importing plans.")
            if existing and not existing.active:
                raise ValueError("The existing machine is archived.")
            pm_name = str(data["pm_name"] or "").strip()
            prepared_row = {
                "plant": plant.pk,
                "department": department.pk,
                "code": code,
                "name": name,
                "tonnage": str(tonnage),
                "commissioned_on": commissioned.isoformat(),
                "existing_version": existing.version if existing else None,
                "plan": None,
            }
            if pm_name:
                if len(pm_name) > 150:
                    raise ValueError("PM name is too long.")
                interval = int(data["interval"])
                if (
                    str(interval) != str(data["interval"]).strip()
                    or not 1 <= interval <= 3650
                    or data["unit"] not in ("days", "weeks", "months")
                ):
                    raise ValueError("Interval must be a positive whole number and unit days/weeks/months.")
                due = _date(data["first_due"])
                validate_schedule(due, commissioned)
                tech = User.objects.get(username=data["technician_id"], is_active=True)
                approver = User.objects.get(username=data["approver_id"], is_active=True)
                for person, role in [(tech, "technician"), (approver, "approver")]:
                    if not Membership.objects.filter(user=person, plant=plant, role=role).exists():
                        raise ValueError(f"{person.username} is not a {role} at this plant.")
                key = (*machine_key, pm_name)
                if key in seen_plans or (existing and PMPlan.objects.filter(machine=existing, name=pm_name).exists()):
                    raise ValueError("This PM plan already exists or is repeated in the workbook.")
                seen_plans.add(key)
                prepared_row["plan"] = {
                    "name": pm_name,
                    "first_due": due.isoformat(),
                    "interval": interval,
                    "unit": data["unit"],
                    "technician_id": tech.pk,
                    "approver_id": approver.pk,
                }
            elif existing:
                raise ValueError("This machine already exists; include a new PM plan or edit it in the app.")
            prepared.append(prepared_row)
        except (
            ValidationError,
            ValueError,
            TypeError,
            InvalidOperation,
            Plant.DoesNotExist,
            Department.DoesNotExist,
            User.DoesNotExist,
        ) as exc:
            errors.append(f"Row {number}: {str(exc) or 'Unknown plant, department or user.'}")
    return {"rows": rows, "prepared": prepared, "errors": errors}


def preview_import(user, workbook):
    require_admin(user)
    raw = workbook.read(5 * 1024 * 1024 + 1)
    if len(raw) > 5 * 1024 * 1024:
        raise ValidationError("Workbook must be no larger than 5 MB.")
    try:
        with ZipFile(BytesIO(raw)) as archive:
            if sum(info.file_size for info in archive.infolist()) > 30 * 1024 * 1024:
                raise ValidationError("Workbook expands beyond the 30 MB safety limit.")
        wb = load_workbook(BytesIO(raw), read_only=True, data_only=False)
        sheet = wb.active
        iterator = sheet.iter_rows(values_only=True)
        header = next(iterator, ())
        if list(header) != IMPORT_HEADERS:
            raise ValidationError("Use the supplied template without changing its column headings.")
        rows = []
        for values in iterator:
            if all(value is None for value in values):
                continue
            if len(rows) >= 1000:
                raise ValidationError("Import at most 1,000 rows at a time.")
            row = [
                value.date().isoformat()
                if isinstance(value, datetime)
                else value.isoformat()
                if isinstance(value, date)
                else str(value).strip()
                if value is not None
                else ""
                for value in values
            ]
            if any(value.startswith("=") for value in row):
                raise ValidationError("Formulas are not accepted; upload values only.")
            rows.append(row)
        wb.close()
    except (BadZipFile, KeyError, OSError, ValueError) as exc:
        raise ValidationError("Upload a valid .xlsx workbook.") from exc
    if not rows:
        raise ValidationError("The workbook contains no records.")
    return _validate_rows(rows)


def commit_import(user, preview):
    require_admin(user)
    if preview.get("errors") or not preview.get("rows"):
        raise ValidationError("Fix the preview errors before importing.")
    try:
        with transaction.atomic():
            # Serialize imports/admin master writes using plant rows, then re-read all dependencies.
            list(Plant.objects.select_for_update().order_by("pk"))
            result = _validate_rows(preview["rows"])
            if result["errors"] or result["prepared"] != preview["prepared"]:
                raise ValidationError("Records changed since preview. Upload the workbook again for a fresh preview.")
            counts = {"machines": 0, "plans": 0}
            for row in result["prepared"]:
                machine = Machine.objects.filter(plant_id=row["plant"], code=row["code"]).first()
                if machine is None:
                    machine = Machine.objects.create(
                        plant_id=row["plant"],
                        department_id=row["department"],
                        code=row["code"],
                        name=row["name"],
                        tonnage=row["tonnage"],
                        commissioned_on=row["commissioned_on"],
                    )
                    audit(user, machine, "import.machine")
                    counts["machines"] += 1
                if row["plan"]:
                    plan = PMPlan.objects.create(machine=machine, **row["plan"])
                    audit(user, plan, "import.plan", plant_id=machine.plant_id)
                    counts["plans"] += 1
            return counts
    except IntegrityError as exc:
        raise ValidationError("Another update conflicted with this import. Nothing was saved; preview again.") from exc


def safe_cell(value):
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def finish_workbook(wb):
    for sheet in wb:
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="12332E")
            cell.alignment = Alignment(wrap_text=True)
        for column in sheet.columns:
            sheet.column_dimensions[column[0].column_letter].width = min(
                45, max(16, max(len(str(c.value or "")) for c in column) + 2)
            )
    out = BytesIO()
    wb.save(out)
    return out.getvalue()


def import_template():
    wb = Workbook()
    wb.active.title = "Machines and PM"
    wb.active.append(IMPORT_HEADERS)
    return finish_workbook(wb)


def export_report(report):
    wb = Workbook()
    summary = wb.active
    summary.title = "Summary"
    summary.append(["Metric", "Value"])
    for key in [
        "start",
        "end",
        "machine_count",
        "active_machine_count",
        "pm_due",
        "pm_machine_count",
        "pm_completed",
        "pm_pending",
        "pm_awaiting",
        "pm_overdue",
        "compliance",
        "breakdown_count",
        "downtime_hours",
    ]:
        summary.append([key.replace("_", " ").title(), report[key]])
    sheet = wb.create_sheet("Machines")
    sheet.append(
        [
            "Plant",
            "Department",
            "Machine ID",
            "Machine",
            "Breakdowns",
            "Downtime (h)",
            "Running hours",
            "Runtime complete",
            "MTTR (h)",
            "MTBF (h)",
        ]
    )
    for row in report["machine_rows"]:
        sheet.append(
            [
                safe_cell(row[key])
                for key in [
                    "plant",
                    "department",
                    "code",
                    "name",
                    "breakdowns",
                    "downtime_hours",
                    "runtime_hours",
                    "runtime_complete",
                    "mttr",
                    "mtbf",
                ]
            ]
        )
    for name, key in [("Departments", "department_rows"), ("Plants", "plant_rows")]:
        sheet = wb.create_sheet(name)
        sheet.append(["Group", "Breakdowns", "Downtime (h)"])
        for row in report[key]:
            sheet.append([safe_cell(row["name"]), row["breakdowns"], row["downtime_hours"]])
    sheet = wb.create_sheet("PM tasks")
    sheet.append(["Machine ID", "PM task", "Due date", "Status", "Completed at (IST)"])
    for task in report["pm_tasks"]:
        sheet.append(
            [
                safe_cell(task.snapshot.get("code", "")),
                safe_cell(task.task_name),
                task.due,
                task.get_status_display(),
                timezone.localtime(task.completed_at).replace(tzinfo=None) if task.completed_at else None,
            ]
        )
    return finish_workbook(wb)
