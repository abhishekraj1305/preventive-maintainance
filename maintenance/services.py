"""All workflow writes pass through these authorization/transaction boundaries."""

import json
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Q
from django.forms.models import model_to_dict
from django.utils import timezone

from .access import require_role, is_admin
from .models import Machine, PMOccurrence, PMSubmission, Breakdown, RuntimeLog, AuditEvent, Membership
from .scheduling import notify


class Conflict(ValidationError):
    def __init__(self):
        super().__init__("This record changed in another session. Reload it before saving again.")


def check_version(obj, version):
    if version is None or obj.version != int(version):
        raise Conflict()


def snapshot(obj):
    result = model_to_dict(obj)
    for key in ("password", "last_login"):
        result.pop(key, None)
    return json.loads(json.dumps(result, cls=DjangoJSONEncoder))


def audit(user, obj, action, before=None, plant_id=None):
    AuditEvent.objects.create(
        actor=user,
        plant_id=plant_id or getattr(obj, "plant_id", None),
        action=action,
        entity=obj._meta.model_name,
        object_id=obj.pk,
        before=before or {},
        after=snapshot(obj),
    )


def require_active(machine):
    if not machine.active or not machine.plant.active:
        raise ValidationError("This machine or plant is archived. An administrator must reactivate it first.")


def record_fields(machine):
    return {
        "machine": machine,
        "plant_id": machine.plant_id,
        "department_id": machine.department_id,
        "snapshot": machine.snapshot(),
    }


def pm_allowed(user, item, action):
    role = "technician" if action == "submit" else "approver"
    # Admin permission does not grant permission to perform or approve maintenance.
    require_role(user, item.plant_id, [role], admin_ok=False)
    expected = item.technician_id if action == "submit" else item.approver_id
    if user.pk != expected:
        raise PermissionDenied("This task is assigned to another user.")


@transaction.atomic
def submit_pm(user, occurrence_id, version, completed_at, notes):
    item = PMOccurrence.objects.select_for_update().get(pk=occurrence_id)
    pm_allowed(user, item, "submit")
    check_version(item, version)
    if item.status not in ("pending", "rejected"):
        raise ValidationError("Only pending or rejected PM work can be submitted.")
    if not notes.strip():
        raise ValidationError("Describe the work completed.")
    if completed_at > timezone.now():
        raise ValidationError("Completion time cannot be in the future.")
    if timezone.localdate(completed_at) < item.machine.commissioned_on:
        raise ValidationError("Completion cannot precede the machine commissioning date.")
    before = snapshot(item)
    submission = PMSubmission.objects.create(
        occurrence=item, submitted_by=user, completed_at=completed_at, notes=notes.strip()
    )
    item.status = "submitted"
    item.completed_at = completed_at
    item.version += 1
    item.save()
    audit(user, item, "pm.submit", before)
    notify(
        item.approver_id,
        item.plant_id,
        f"pm-submission:{submission.pk}",
        "PM awaiting your approval",
        f"{item.snapshot['code']} · {item.task_name} · Submitted by {user.get_full_name() or user.username}",
        f"/pm/{item.pk}/",
    )
    return item


@transaction.atomic
def review_pm(user, occurrence_id, version, decision, reason):
    item = PMOccurrence.objects.select_for_update().get(pk=occurrence_id)
    pm_allowed(user, item, "review")
    check_version(item, version)
    if item.status != "submitted":
        raise ValidationError("This PM task is not awaiting approval.")
    submission = item.submissions.first()
    if submission.submitted_by_id == user.pk:
        raise PermissionDenied("You cannot approve your own submission.")
    if decision not in ("approve", "reject"):
        raise ValidationError("Choose approve or reject.")
    if decision == "reject" and not reason.strip():
        raise ValidationError("A rejection reason is required.")
    before = snapshot(item)
    submission.decision = decision
    submission.reason = reason.strip()
    submission.reviewed_by = user
    submission.reviewed_at = timezone.now()
    submission.save()
    item.status = "approved" if decision == "approve" else "rejected"
    item.version += 1
    item.save()
    audit(user, item, f"pm.{decision}", before)
    notify(
        item.technician_id,
        item.plant_id,
        f"pm-review:{submission.pk}",
        f"PM {item.get_status_display().lower()}",
        f"{item.snapshot['code']} · {item.task_name}. {reason}",
        f"/pm/{item.pk}/",
    )
    return item


@transaction.atomic
def save_breakdown(user, data, pk=None, version=None):
    if pk:
        # Lock parent before incident; every write for one machine serializes here.
        existing = Breakdown.objects.get(pk=pk)
        machine = (
            Machine.objects.select_for_update(of=("self",))
            .select_related("plant", "department")
            .get(pk=existing.machine_id)
        )
        obj = Breakdown.objects.select_for_update().get(pk=pk)
        require_role(user, obj.plant_id, ["technician"])
        check_version(obj, version)
        if obj.status == "closed" and not is_admin(user):
            raise ValidationError("Closed repairs can only be corrected by an administrator.")
        before = snapshot(obj)
        editable = (
            ("occurred_at", "description", "repair_start", "repair_end", "root_cause", "action_taken")
            if is_admin(user)
            else ("repair_start", "repair_end", "root_cause", "action_taken")
        )
        for key in editable:
            if key in data:
                setattr(obj, key, data[key])
        if not is_admin(user):
            obj.technician = user
        obj.version += 1
    else:
        machine = (
            Machine.objects.select_for_update(of=("self",))
            .select_related("plant", "department")
            .get(pk=data["machine"].pk)
        )
        require_role(user, machine.plant_id, ["operator", "technician"])
        require_active(machine)
        obj = Breakdown(
            **record_fields(machine),
            reported_by=user,
            occurred_at=data["occurred_at"],
            description=data["description"].strip(),
        )
        before = None
        if any(data.get(key) for key in ("repair_start", "repair_end", "root_cause", "action_taken")):
            require_role(user, machine.plant_id, ["technician"])
            for key in ("repair_start", "repair_end", "root_cause", "action_taken"):
                if key in data:
                    setattr(obj, key, data[key])
            if not is_admin(user):
                obj.technician = user
    if is_admin(user) and data.get("technician"):
        obj.technician = data["technician"]
    if obj.repair_start:
        if (
            not obj.technician_id
            or not Membership.objects.filter(
                user_id=obj.technician_id, user__is_active=True, plant_id=machine.plant_id, role="technician"
            ).exists()
        ):
            raise ValidationError("Select an active technician assigned to this plant for the repair.")
    now = timezone.now()
    if not obj.description.strip():
        raise ValidationError("Enter a breakdown description.")
    if obj.occurred_at > now or timezone.localdate(obj.occurred_at) < machine.commissioned_on:
        raise ValidationError("Breakdown time must be between commissioning and now.")
    if obj.repair_start and not obj.occurred_at <= obj.repair_start <= now:
        raise ValidationError("Repair start must be between breakdown time and now.")
    if obj.repair_end and (not obj.repair_start or not obj.repair_start <= obj.repair_end <= now):
        raise ValidationError("Repair end must be between repair start and now.")
    if obj.repair_end and (not obj.root_cause.strip() or not obj.action_taken.strip()):
        raise ValidationError("Root cause and action taken are required to close a breakdown.")
    obj.status = "closed" if obj.repair_end else "repair" if obj.repair_start else "open"
    overlap = Breakdown.objects.filter(machine=machine).exclude(pk=pk)
    if obj.repair_end:
        overlap = overlap.filter(occurred_at__lt=obj.repair_end)
    overlap = overlap.filter(Q(repair_end__isnull=True) | Q(repair_end__gt=obj.occurred_at))
    if overlap.exists():
        raise ValidationError("This machine already has an open or overlapping breakdown.")
    obj.full_clean()
    obj.save()
    audit(user, obj, "breakdown.update" if pk else "breakdown.report", before)
    return obj


@transaction.atomic
def save_runtime(user, data, pk=None, version=None):
    machine_id = RuntimeLog.objects.get(pk=pk).machine_id if pk else data["machine"].pk
    machine = Machine.objects.select_for_update(of=("self",)).select_related("plant", "department").get(pk=machine_id)
    require_role(user, machine.plant_id, ["operator", "technician"])
    if pk:
        obj = RuntimeLog.objects.select_for_update().get(pk=pk)
        check_version(obj, version)
        before = snapshot(obj)
        obj.version += 1
    else:
        require_active(machine)
        obj = RuntimeLog(**record_fields(machine), entered_by=user)
        before = None
    obj.date = data["date"]
    obj.hours = Decimal(str(data["hours"]))
    obj.entered_by = user
    if obj.date > timezone.localdate() or obj.date < machine.commissioned_on:
        raise ValidationError("Running-hours date must be between commissioning and today.")
    if not obj.hours.is_finite() or not 0 <= obj.hours <= 24:
        raise ValidationError("Running hours must be between 0 and 24.")
    if RuntimeLog.objects.filter(machine=machine, date=obj.date).exclude(pk=pk).exists():
        raise ValidationError("Hours already exist for this machine and date. Edit the existing entry.")
    obj.full_clean()
    obj.save()
    audit(user, obj, "runtime.update" if pk else "runtime.create", before)
    return obj
