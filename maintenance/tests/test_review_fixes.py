from io import StringIO
from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.backends.db import SessionStore
from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory

from maintenance.models import User, Machine
from maintenance.views.accounts import password
from .test_excel import workbook, row


def test_new_breakdown_detail_renders_before_technician_assignment(client, factory):
    from maintenance.services import save_breakdown
    from django.utils import timezone

    incident = save_breakdown(
        factory.operator, {"machine": factory.machine, "occurred_at": timezone.now(), "description": "New fault"}
    )
    client.force_login(factory.tech)
    assert client.get(f"/breakdowns/{incident.pk}/").status_code == 200


def password_request(user):
    req = RequestFactory().post(
        "/password/",
        {
            "old_password": "StrongDemo-2026!",
            "new_password1": "UpdatedSecure-2026!",
            "new_password2": "UpdatedSecure-2026!",
        },
    )
    req.user = user  # Deliberately captured before another admin changes the account.
    req.session = SessionStore()
    req._messages = FallbackStorage(req)
    return req


def test_password_change_does_not_restore_revoked_account(factory):
    req = password_request(factory.admin)
    User.objects.filter(pk=factory.admin.pk).update(is_active=False, is_superuser=False, version=2)
    response = password(req)
    factory.admin.refresh_from_db()
    assert response.status_code == 302
    assert not factory.admin.is_active
    assert not factory.admin.is_superuser
    assert factory.admin.version == 2


def test_password_change_preserves_concurrent_demotion(factory):
    req = password_request(factory.admin)
    User.objects.filter(pk=factory.admin.pk).update(is_superuser=False, version=2)
    password(req)
    factory.admin.refresh_from_db()
    assert not factory.admin.is_superuser
    assert factory.admin.version == 3
    assert factory.admin.check_password("UpdatedSecure-2026!")


def test_password_change_revalidates_after_admin_reset(factory):
    req = password_request(factory.tech)
    current = User.objects.get(pk=factory.tech.pk)
    current.set_password("AdminReplacement-2026!")
    current.version = 2
    current.must_change_password = True
    current.save()
    password(req)
    factory.tech.refresh_from_db()
    assert factory.tech.check_password("AdminReplacement-2026!")
    assert factory.tech.must_change_password
    assert factory.tech.version == 2


def test_old_import_tab_cannot_confirm_newer_workbook(client, factory):
    client.force_login(factory.admin)
    first = row(factory, "IMPORT-A")
    second = row(factory, "IMPORT-B")
    response = client.post("/import/", {"workbook": SimpleUploadedFile("a.xlsx", workbook([first]).read())})
    assert response.status_code == 200
    old_id = client.session["import_preview"].get("preview_id", "")
    client.post("/import/", {"workbook": SimpleUploadedFile("b.xlsx", workbook([second]).read())})
    assert client.post("/import/commit/", {"preview_id": old_id}).status_code == 302
    assert not Machine.objects.filter(code__in=["IMPORT-A", "IMPORT-B"]).exists()
    new_id = client.session["import_preview"]["preview_id"]
    assert client.post("/import/commit/", {"preview_id": new_id}).status_code == 302
    assert Machine.objects.filter(code="IMPORT-B").exists()


def test_bootstrap_does_not_recreate_or_require_retired_account(factory, monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_USERNAME", factory.admin.username)
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "RetainedBootstrap-2026!")
    User.objects.create_superuser("replacement.admin", password="Replacement-2026!")
    factory.admin.is_active = False
    factory.admin.is_superuser = False
    factory.admin.save()
    call_command("bootstrap_app", stdout=StringIO())
    factory.admin.username = "retired.admin"
    factory.admin.save()
    call_command("bootstrap_app", stdout=StringIO())
    assert not User.objects.filter(username="admin").exists()
    assert User.objects.filter(is_active=True, is_superuser=True).count() == 1
