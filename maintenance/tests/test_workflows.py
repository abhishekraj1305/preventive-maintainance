from datetime import timedelta
from decimal import Decimal

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.utils import timezone
from maintenance.access import scoped_machines
from maintenance.models import PMOccurrence, PMSubmission, Notification, AuditEvent, Breakdown, RuntimeLog
from maintenance.scheduling import reconcile
from maintenance import services


def task(factory):
    reconcile(factory.tech)
    return PMOccurrence.objects.get(plan=factory.plan)


def test_scope_and_reminders_survive_repeated_refresh(factory):
    assert list(scoped_machines(factory.outsider)) == [factory.other]
    task(factory)
    reconcile(factory.tech)
    assert PMOccurrence.objects.count() == 1
    assert Notification.objects.count() == 1


def test_idle_catchup_preserves_missed_cycles(factory):
    factory.plan.first_due = timezone.localdate() - timedelta(days=30)
    factory.plan.interval = 10
    factory.plan.unit = "days"
    factory.plan.save()
    reconcile(factory.tech)
    assert PMOccurrence.objects.count() == 4
    assert PMOccurrence.objects.filter(due__lt=timezone.localdate()).count() == 3


def test_pm_reject_resubmit_approve_preserves_history(factory):
    occurrence = task(factory)
    when = timezone.now() - timedelta(minutes=2)
    services.submit_pm(factory.tech, occurrence.pk, 1, when, "Lubricated bearings")
    services.review_pm(factory.approver, occurrence.pk, 2, "reject", "Add oil grade")
    services.submit_pm(factory.tech, occurrence.pk, 3, when, "ISO 68 oil; inspected seals")
    services.review_pm(factory.approver, occurrence.pk, 4, "approve", "")
    occurrence.refresh_from_db()
    assert occurrence.status == "approved"
    assert occurrence.version == 5
    assert PMSubmission.objects.count() == 2
    assert PMSubmission.objects.filter(decision="reject").get().reason == "Add oil grade"
    assert AuditEvent.objects.count() == 4
    assert factory.plan.first_due == occurrence.due


def test_wrong_role_and_other_plant_cannot_submit(factory):
    occurrence = task(factory)
    for user in (factory.operator, factory.approver, factory.outsider):
        with pytest.raises(PermissionDenied):
            services.submit_pm(user, occurrence.pk, 1, timezone.now(), "Worked")


def test_duplicate_submission_and_empty_rejection_are_rejected(factory):
    occurrence = task(factory)
    services.submit_pm(factory.tech, occurrence.pk, 1, timezone.now(), "Work done")
    with pytest.raises(services.Conflict):
        services.submit_pm(factory.tech, occurrence.pk, 1, timezone.now(), "Duplicate")
    with pytest.raises(ValidationError):
        services.review_pm(factory.approver, occurrence.pk, 2, "reject", "")
    assert PMSubmission.objects.count() == 1


def test_self_approval_denied_even_to_admin(factory):
    occurrence = task(factory)
    services.submit_pm(factory.tech, occurrence.pk, 1, timezone.now(), "Done")
    factory.tech.is_superuser = True
    factory.tech.save()
    with pytest.raises(PermissionDenied):
        services.review_pm(factory.tech, occurrence.pk, 2, "approve", "")


def test_future_completion_is_rejected(factory):
    occurrence = task(factory)
    with pytest.raises(ValidationError):
        services.submit_pm(factory.tech, occurrence.pk, 1, timezone.now() + timedelta(days=1), "Done")


def test_breakdown_repair_calculates_separate_durations(factory):
    now = timezone.now()
    b = services.save_breakdown(
        factory.operator,
        {"machine": factory.machine, "occurred_at": now - timedelta(hours=4), "description": "Pressure loss"},
    )
    b = services.save_breakdown(factory.tech, {"repair_start": now - timedelta(hours=3)}, b.pk, 1)
    b = services.save_breakdown(
        factory.tech,
        {"repair_end": now - timedelta(hours=1), "root_cause": "Seal worn", "action_taken": "Replaced seal"},
        b.pk,
        2,
    )
    assert b.status == "closed"
    assert b.downtime_hours == pytest.approx(3)
    assert b.repair_hours == pytest.approx(2)
    assert b.technician == factory.tech


def test_breakdown_duplicate_and_crossplant_injection_rejected(factory):
    data = {"machine": factory.machine, "occurred_at": timezone.now(), "description": "Stopped"}
    services.save_breakdown(factory.operator, data)
    with pytest.raises(ValidationError):
        services.save_breakdown(factory.operator, data)
    with pytest.raises(PermissionDenied):
        services.save_breakdown(factory.operator, {**data, "machine": factory.other})
    assert Breakdown.objects.count() == 1


def test_operator_cannot_close_and_invalid_timestamps_rejected(factory):
    now = timezone.now()
    b = services.save_breakdown(
        factory.operator, {"machine": factory.machine, "occurred_at": now, "description": "Fault"}
    )
    with pytest.raises(PermissionDenied):
        services.save_breakdown(factory.operator, {"repair_start": now}, b.pk, 1)
    with pytest.raises(ValidationError):
        services.save_breakdown(factory.tech, {"repair_start": now - timedelta(hours=1)}, b.pk, 1)


def test_runtime_limits_unique_days_and_scope(factory):
    data = {"machine": factory.machine, "date": timezone.localdate(), "hours": Decimal("8.5")}
    log = services.save_runtime(factory.operator, data)
    assert log.hours == Decimal("8.5")
    for invalid in ({**data, "hours": 25}, {**data, "date": timezone.localdate() + timedelta(days=1)}):
        with pytest.raises(ValidationError):
            services.save_runtime(factory.operator, invalid)
    with pytest.raises(ValidationError):
        services.save_runtime(factory.operator, data)
    with pytest.raises(PermissionDenied):
        services.save_runtime(factory.outsider, data)
    assert RuntimeLog.objects.count() == 1
