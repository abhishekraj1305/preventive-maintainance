from io import StringIO
from django.core.management import call_command
from maintenance.models import User, Plant, Machine, PMOccurrence, Breakdown
import pytest


@pytest.mark.django_db
def test_bootstrap_is_idempotent_and_does_not_reset_existing_password(monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ADMIN_USERNAME", "workspace.admin")
    monkeypatch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "InitialSecure-2026!")
    call_command("bootstrap_app", stdout=StringIO())
    user = User.objects.get(username="workspace.admin")
    assert user.is_superuser
    assert user.must_change_password
    user.set_password("ChangedSecure-2026!")
    user.save()
    call_command("bootstrap_app", stdout=StringIO())
    user.refresh_from_db()
    assert user.check_password("ChangedSecure-2026!")


@pytest.mark.django_db
def test_demo_seed_has_two_plants_real_workflows_and_is_idempotent(settings, monkeypatch):
    settings.DEMO_MODE = True
    monkeypatch.setenv("DEMO_PASSWORD", "DemoTemporary-2026!")
    call_command("seed_demo", stdout=StringIO())
    assert Plant.objects.count() == 2
    assert Machine.objects.count() == 8
    assert PMOccurrence.objects.filter(status="submitted").exists()
    assert Breakdown.objects.filter(status="repair").exists()
    before = (User.objects.count(), Machine.objects.count(), PMOccurrence.objects.count(), Breakdown.objects.count())
    call_command("seed_demo", stdout=StringIO())
    after = (User.objects.count(), Machine.objects.count(), PMOccurrence.objects.count(), Breakdown.objects.count())
    assert after == before


@pytest.mark.django_db
def test_seed_refuses_non_demo_environment(settings, monkeypatch):
    settings.DEMO_MODE = False
    from django.core.management.base import CommandError

    with pytest.raises(CommandError):
        call_command("seed_demo")
