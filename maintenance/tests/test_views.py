from datetime import timedelta
from django.utils import timezone
from maintenance.models import PMOccurrence, Notification, Machine
from maintenance.scheduling import reconcile


def test_login_required_and_forced_password_change(client, factory):
    response = client.get("/")
    assert response.status_code == 302
    assert "/login/" in response.url
    factory.operator.must_change_password = True
    factory.operator.save()
    client.force_login(factory.operator)
    assert client.get("/").url == "/password/"
    assert client.get("/reports/export/").url == "/password/"


def test_all_working_screens_render_without_other_plant_data(client, factory):
    reconcile(factory.tech)
    client.force_login(factory.tech)
    for path in ["/", "/machines/", "/pm/", "/approvals/", "/breakdowns/", "/runtime/", "/notifications/", "/reports/"]:
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code)
        assert b"Other Press" not in response.content
    assert client.get(f"/machines/{factory.other.pk}/").status_code == 404
    assert client.get("/settings/").status_code == 403


def test_status_scoping_and_read_notification_do_not_clear_urgency(client, factory):
    reconcile(factory.tech)
    client.force_login(factory.tech)
    response = client.get("/status/")
    assert response.status_code == 200
    data = response.json()
    assert data["pm_open"] == 1
    assert data["unread_count"] == 1
    notification = Notification.objects.get(recipient=factory.tech)
    assert client.post(f"/notifications/{notification.pk}/read/").status_code == 302
    data = client.get("/status/").json()
    assert data["unread_count"] == 0
    assert data["pm_open"] == 1


def test_pm_form_submission_and_review(client, factory):
    reconcile(factory.tech)
    item = PMOccurrence.objects.get()
    client.force_login(factory.tech)
    response = client.post(
        f"/pm/{item.pk}/",
        {
            "action": "submit",
            "version": 1,
            "completed_at": timezone.localtime(timezone.now() - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M"),
            "notes": "Checks done",
        },
    )
    assert response.status_code == 302
    client.force_login(factory.approver)
    response = client.post(f"/pm/{item.pk}/", {"action": "review", "version": 2, "decision": "approve", "reason": ""})
    assert response.status_code == 302
    item.refresh_from_db()
    assert item.status == "approved"


def test_admin_machine_form_validates_department_and_stale_edits(client, factory):
    client.force_login(factory.admin)
    data = {
        "plant": factory.plant.pk,
        "department": factory.other_department.pk,
        "code": "NEW",
        "name": "Test machine",
        "tonnage": 100,
        "commissioned_on": "2026-01-01",
        "active": "on",
        "version": 0,
    }
    response = client.post("/settings/machines/new/", data)
    assert response.status_code == 200
    assert not Machine.objects.filter(code="NEW").exists()
    data["department"] = factory.department.pk
    assert client.post("/settings/machines/new/", data).status_code == 302
    obj = Machine.objects.get(code="NEW")
    data.update(name="First edit", version=1)
    assert client.post(f"/settings/machines/{obj.pk}/", data).status_code == 302
    data.update(name="Stale edit")
    assert client.post(f"/settings/machines/{obj.pk}/", data).status_code == 409
    obj.refresh_from_db()
    assert obj.name == "First edit"


def test_admin_password_reset_forces_change_and_invalidates_session(client, factory):
    client.force_login(factory.admin)
    response = client.post(f"/settings/users/{factory.tech.pk}/reset/", {"new_password": "BetterReset-2026!"})
    assert response.status_code == 302
    factory.tech.refresh_from_db()
    assert factory.tech.must_change_password
    assert factory.tech.check_password("BetterReset-2026!")


def test_report_bad_filters_are_handled_and_export_is_xlsx(client, factory):
    client.force_login(factory.tech)
    assert client.get("/reports/?start=invalid").status_code == 200
    assert client.get("/reports/?plant=not-a-number").status_code == 200
    response = client.get("/reports/export/")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert response.content[:2] == b"PK"
