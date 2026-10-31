from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from django.test import Client
from django.db import connection, close_old_connections
from django.core.exceptions import ValidationError
from django.utils import timezone

from maintenance.models import User, PMOccurrence, PMSubmission, Notification, Breakdown
from maintenance.scheduling import reconcile
from maintenance.services import submit_pm, save_breakdown, Conflict


def test_csrf_required_for_state_changes(factory):
    client = Client(enforce_csrf_checks=True)
    client.force_login(factory.operator)
    assert client.post("/breakdowns/new/", {"machine": factory.machine.pk}).status_code == 403


def test_login_throttles_and_does_not_accept_correct_password_while_locked(client, factory):
    for _ in range(5):
        response = client.post("/login/", {"username": factory.operator.username, "password": "wrong"})
    assert response.status_code == 429
    response = client.post("/login/", {"username": factory.operator.username, "password": "StrongDemo-2026!"})
    assert response.status_code == 429


def test_user_session_invalid_after_admin_password_reset(factory):
    staff, admin = Client(), Client()
    staff.force_login(factory.tech)
    admin.force_login(factory.admin)
    assert staff.get("/").status_code == 200
    admin.post(f"/settings/users/{factory.tech.pk}/reset/", {"new_password": "ResetSecure-2026!"})
    response = staff.get("/")
    assert response.status_code == 302 and "/login/" in response.url


def test_other_plant_cannot_read_notification_or_pm_details(client, factory):
    reconcile(factory.tech)
    task = PMOccurrence.objects.get()
    note = Notification.objects.get()
    client.force_login(factory.outsider)
    assert client.get(f"/pm/{task.pk}/").status_code == 404
    assert client.post(f"/notifications/{note.pk}/read/").status_code == 404
    assert client.get(f"/reports/export/?plant={factory.plant.pk}").status_code == 200
    from openpyxl import load_workbook
    from io import BytesIO

    workbook = load_workbook(BytesIO(client.get(f"/reports/export/?plant={factory.plant.pk}").content))
    assert workbook["Machines"].max_row == 1


def parallel(function):
    barrier = Barrier(2)

    def run():
        close_old_connections()
        try:
            barrier.wait(timeout=10)
            return function()
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(lambda _: run(), range(2)))


@pytest.mark.django_db(transaction=True)
def test_concurrent_reconcile_does_not_duplicate_occurrences_or_notifications(factory):
    if connection.vendor != "postgresql":
        pytest.skip("Row-lock integration test requires PostgreSQL")
    parallel(lambda: reconcile(User.objects.get(pk=factory.tech.pk)))
    assert PMOccurrence.objects.count() == 1
    assert Notification.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_submissions_accept_only_one(factory):
    if connection.vendor != "postgresql":
        pytest.skip("Row-lock integration test requires PostgreSQL")
    reconcile(factory.tech)
    pk = PMOccurrence.objects.get().pk

    def attempt():
        try:
            submit_pm(User.objects.get(pk=factory.tech.pk), pk, 1, timezone.now(), "Work completed")
            return "accepted"
        except Conflict:
            return "conflict"

    assert sorted(parallel(attempt)) == ["accepted", "conflict"]
    assert PMSubmission.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_breakdown_reports_accept_only_one(factory):
    if connection.vendor != "postgresql":
        pytest.skip("Row-lock integration test requires PostgreSQL")

    def attempt():
        try:
            save_breakdown(
                User.objects.get(pk=factory.operator.pk),
                {
                    "machine": factory.machine,
                    "occurred_at": timezone.now() - timedelta(minutes=1),
                    "description": "Stopped",
                },
            )
            return "accepted"
        except ValidationError:
            return "conflict"

    assert sorted(parallel(attempt)) == ["accepted", "conflict"]
    assert Breakdown.objects.count() == 1
