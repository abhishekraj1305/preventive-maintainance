from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.utils import timezone

from maintenance.access import plant_ids, is_admin
from maintenance.models import Plant, Department, Notification, PMOccurrence, Breakdown, Membership
from maintenance.scheduling import reconcile


def app_view(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if request.user.must_change_password:
            return redirect("password")
        reconcile(request.user)
        return view(request, *args, **kwargs)

    return wrapper


def admin_view(view):
    @app_view
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not is_admin(request.user):
            raise PermissionDenied("Administrator access is required.")
        return view(request, *args, **kwargs)

    return wrapper


def selected(request, name):
    value = request.GET.get(name, "")
    try:
        return int(value) if value else None
    except (ValueError, TypeError):
        return None


def apply_filters(qs, request, machine_field="machine_id"):
    for key, field in [("plant", "plant_id"), ("department", "department_id"), ("machine", machine_field)]:
        value = selected(request, key)
        if value:
            qs = qs.filter(**{field: value})
    return qs


def live_data(request):
    ids = plant_ids(request.user)
    tasks = apply_filters(PMOccurrence.objects.filter(plant_id__in=ids), request)
    open_tasks = tasks.exclude(status="approved")
    incidents = apply_filters(Breakdown.objects.filter(plant_id__in=ids), request)
    inbox = Notification.objects.filter(recipient=request.user, plant_id__in=ids)
    plant = selected(request, "plant")
    if plant:
        inbox = inbox.filter(plant_id=plant)
    return {
        "server_now": timezone.now().isoformat(),
        "pm_open": open_tasks.count(),
        "overdue": open_tasks.filter(due__lt=timezone.localdate()).count(),
        "awaiting": tasks.filter(status="submitted").count(),
        "breakdown_open": incidents.exclude(status="closed").count(),
        "unread_count": inbox.filter(read_at__isnull=True).count(),
        "pm_states": list(tasks.order_by("-updated_at").values("id", "status", "version")[:200]),
        "breakdown_states": [
            {
                "id": b.pk,
                "status": b.status,
                "version": b.version,
                "repair_end": b.repair_end.isoformat() if b.repair_end else None,
            }
            for b in incidents.order_by("-updated_at")[:200]
        ],
    }


def page(request, template, context=None, status=200):
    ids = plant_ids(request.user)
    roles = set(Membership.objects.filter(user=request.user).values_list("role", flat=True))
    context = {
        "plants": Plant.objects.filter(pk__in=ids),
        "departments": Department.objects.filter(plant_id__in=ids),
        "selected_plant": selected(request, "plant"),
        "selected_department": selected(request, "department"),
        "is_admin": is_admin(request.user),
        "can_report": bool(roles & {"operator", "technician"}) or is_admin(request.user),
        "today": timezone.localdate(),
        "live": live_data(request),
        **(context or {}),
    }
    return render(request, template, context, status=status)


def form_errors(form, exc):
    for message in exc.messages:
        form.add_error(None, message)
