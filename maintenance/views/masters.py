from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction, IntegrityError
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.debug import sensitive_post_parameters

from maintenance.models import User, Plant, Department, Membership, Machine, PMPlan, PMOccurrence, AuditEvent
from maintenance.forms import (
    PlantForm,
    DepartmentForm,
    MachineForm,
    PlanForm,
    UserForm,
    MembershipForm,
    ResetPasswordForm,
)
from maintenance.services import audit, snapshot, check_version, Conflict
from maintenance.scheduling import notify
from .common import admin_view, page, form_errors

MASTERS = {
    "plants": (Plant, PlantForm, "Plant"),
    "departments": (Department, DepartmentForm, "Department"),
    "machines": (Machine, MachineForm, "Machine"),
    "plans": (PMPlan, PlanForm, "PM plan"),
    "users": (User, UserForm, "User"),
    "memberships": (Membership, MembershipForm, "Plant role"),
}


@admin_view
def settings_home(request):
    return page(
        request,
        "settings.html",
        {
            "title": "Administration",
            "nav": "settings",
            "all_plants": Plant.objects.all(),
            "all_departments": Department.objects.select_related("plant"),
            "users": User.objects.order_by("username"),
            "memberships": Membership.objects.select_related("user", "plant").order_by("plant__name", "user__username"),
            "plans": PMPlan.objects.select_related("machine", "technician", "approver"),
            "audit_events": AuditEvent.objects.select_related("actor", "plant")[:50],
        },
    )


@sensitive_post_parameters("temporary_password")
@admin_view
def master_edit(request, kind, pk=None):
    if kind not in MASTERS:
        from django.http import Http404

        raise Http404()
    model, form_class, label = MASTERS[kind]
    instance = get_object_or_404(model, pk=pk) if pk else model()
    form = form_class(request.POST or None, instance=instance)
    status = 200
    if request.method == "POST":
        try:
            with transaction.atomic():
                # Same lock order as workbook commits; serialize configuration changes.
                list(Plant.objects.select_for_update().order_by("pk"))
                instance = model.objects.select_for_update().get(pk=pk) if pk else model()
                before = snapshot(instance) if pk else None
                form = form_class(request.POST, instance=instance)
                if form.is_valid():
                    obj = form.save(commit=False)
                    if pk and hasattr(obj, "version"):
                        check_version(obj, form.cleaned_data.get("version"))
                        obj.version += 1
                    if kind == "users":
                        if pk == request.user.pk and (not obj.is_active or not obj.is_superuser):
                            raise ValidationError("You cannot deactivate or demote your own administrator account.")
                        obj.is_staff = obj.is_superuser
                        if not pk:
                            obj.set_password(form.cleaned_data["temporary_password"])
                            obj.must_change_password = True
                    if kind == "plans" and set(form.changed_data) & {"first_due", "interval", "unit"}:
                        obj.next_index = 0
                    obj.save()
                    form.save_m2m()
                    plant_id = obj.machine.plant_id if kind == "plans" else getattr(obj, "plant_id", None)
                    audit(request.user, obj, f"{kind}.update" if pk else f"{kind}.create", before, plant_id)
                    if kind == "plans" and pk and set(form.changed_data) & {"technician", "approver"}:
                        for task in (
                            PMOccurrence.objects.select_for_update().filter(plan=obj).exclude(status="approved")
                        ):
                            old = snapshot(task)
                            task.technician = obj.technician
                            task.approver = obj.approver
                            task.version += 1
                            task.save()
                            audit(request.user, task, "pm.reassign", old)
                            recipient = task.approver_id if task.status == "submitted" else task.technician_id
                            notify(
                                recipient,
                                task.plant_id,
                                f"pm-assigned:{task.pk}:{task.version}",
                                "PM task assigned to you",
                                f"{task.snapshot['code']} · {task.task_name}",
                                f"/pm/{task.pk}/",
                            )
                    messages.success(request, f"{label} saved.")
                    return redirect("machine_detail", pk=obj.pk) if kind == "machines" else redirect("settings")
        except (ValidationError, IntegrityError) as exc:
            if isinstance(exc, IntegrityError):
                exc = ValidationError("Another record uses the same unique details. Reload and try again.")
            form_errors(form, exc)
            status = 409 if isinstance(exc, Conflict) else 200
    return page(
        request,
        "form.html",
        {
            "title": f"{'Edit' if pk else 'Add'} {label.lower()}",
            "form": form,
            "subtitle": "Changes are recorded in the audit history.",
            "back_url": "/settings/",
            "nav": "settings",
        },
        status,
    )


@sensitive_post_parameters()
@admin_view
def reset_password(request, pk):
    target = get_object_or_404(User, pk=pk)
    form = ResetPasswordForm(request.POST or None, target_user=target)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            target = User.objects.select_for_update().get(pk=pk)
            target.set_password(form.cleaned_data["new_password"])
            target.must_change_password = True
            target.version += 1
            target.save()
            audit(request.user, target, "account.password_reset")
        # Django invalidates previous sessions through the password hash.
        messages.success(request, f"Password reset for {target.username}. They must change it at the next login.")
        return redirect("settings")
    return page(
        request,
        "form.html",
        {
            "title": f"Reset password · {target.username}",
            "subtitle": "Give this temporary password directly to the user. No email is sent.",
            "form": form,
            "back_url": "/settings/",
            "nav": "settings",
        },
    )
