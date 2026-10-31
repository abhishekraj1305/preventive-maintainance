from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone
from maintenance.models import User, Plant, Department, Membership, Machine, PMPlan


@pytest.fixture(autouse=True)
def test_settings(settings):
    settings.SECURE_SSL_REDIRECT = False
    settings.STORAGES = {
        "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture
def factory(db):
    p = Plant.objects.create(code="P1", name="North Works")
    q = Plant.objects.create(code="P2", name="South Works")
    d = Department.objects.create(plant=p, code="PRESS", name="Press shop")
    e = Department.objects.create(plant=q, code="PRESS", name="Press shop")
    admin = User.objects.create_user(
        "admin", password="StrongDemo-2026!", is_superuser=True, must_change_password=False
    )
    users = {}
    for name, role in [("operator", "operator"), ("tech", "technician"), ("approver", "approver")]:
        u = User.objects.create_user(name, password="StrongDemo-2026!", must_change_password=False)
        Membership.objects.create(user=u, plant=p, role=role)
        users[name] = u
    outsider = User.objects.create_user("outsider", password="StrongDemo-2026!", must_change_password=False)
    Membership.objects.create(user=outsider, plant=q, role="technician")
    machine = Machine.objects.create(
        plant=p,
        department=d,
        code="PR-01",
        name="Hydraulic Press",
        tonnage=150,
        commissioned_on=timezone.localdate() - timedelta(days=365),
    )
    other = Machine.objects.create(plant=q, department=e, code="PR-02", name="Other Press", tonnage=200)
    plan = PMPlan.objects.create(
        machine=machine,
        name="Lubrication",
        first_due=timezone.localdate(),
        interval=1,
        unit="months",
        technician=users["tech"],
        approver=users["approver"],
    )
    return SimpleNamespace(
        plant=p,
        other_plant=q,
        department=d,
        other_department=e,
        machine=machine,
        other=other,
        plan=plan,
        admin=admin,
        outsider=outsider,
        **users,
    )
