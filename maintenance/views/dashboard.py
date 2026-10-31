from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.db.models import Q

from maintenance.access import scoped, scoped_machines
from maintenance.models import PMOccurrence, Breakdown, RuntimeLog, AuditEvent
from maintenance.reporting import build_report
from .common import app_view, page, apply_filters, selected, live_data
from django.utils import timezone


@app_view
def dashboard(request):
    today = timezone.localdate()
    report = build_report(request.user, today.replace(day=1), today, selected(request, "plant"))
    tasks = (
        apply_filters(scoped(PMOccurrence, request.user), request).exclude(status="approved").select_related("machine")
    )
    incidents = (
        apply_filters(scoped(Breakdown, request.user), request)
        .exclude(status="closed")
        .select_related("machine", "reported_by")
    )
    return page(
        request,
        "dashboard.html",
        {
            "title": "Maintenance overview",
            "report": report,
            "tasks": tasks[:6],
            "incidents": incidents[:4],
            "nav": "dashboard",
        },
    )


@app_view
def status(request):
    response = JsonResponse(live_data(request))
    response["Cache-Control"] = "no-store"
    return response


@app_view
def machines(request):
    qs = apply_filters(scoped_machines(request.user), request, "pk")
    search = request.GET.get("q", "").strip()
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(code__icontains=search))
    return page(
        request, "machines.html", {"title": "Machine directory", "machines": qs, "query": search, "nav": "machines"}
    )


@app_view
def machine_detail(request, pk):
    machine = get_object_or_404(scoped_machines(request.user), pk=pk)
    return page(
        request,
        "machine_detail.html",
        {
            "title": machine.name,
            "machine": machine,
            "nav": "machines",
            "plans": machine.plans.select_related("technician", "approver"),
            "tasks": scoped(PMOccurrence, request.user).filter(machine=machine).order_by("-due")[:100],
            "incidents": scoped(Breakdown, request.user).filter(machine=machine)[:100],
            "runtime": scoped(RuntimeLog, request.user).filter(machine=machine)[:30],
            "history": AuditEvent.objects.filter(plant_id=machine.plant_id, entity="machine", object_id=pk)[:20],
        },
    )
