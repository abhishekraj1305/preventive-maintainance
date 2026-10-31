from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from maintenance.access import scoped, is_admin, plant_ids
from maintenance.models import PMOccurrence, Breakdown, RuntimeLog, Notification, Membership
from maintenance.forms import SubmissionForm, ReviewForm, BreakdownForm, RepairForm, RuntimeForm
from maintenance.services import submit_pm, review_pm, save_breakdown, save_runtime, Conflict
from .common import app_view, page, apply_filters, form_errors


@app_view
def pm_list(request):
    qs = apply_filters(scoped(PMOccurrence, request.user), request).select_related("machine", "technician")
    state = request.GET.get("state", "open")
    if state == "open":
        qs = qs.exclude(status="approved")
    elif state in PMOccurrence.Status.values:
        qs = qs.filter(status=state)
    return page(request, "pm_list.html", {"title": "Preventive maintenance", "tasks": qs, "state": state, "nav": "pm"})


@app_view
def approvals(request):
    qs = (
        apply_filters(scoped(PMOccurrence, request.user), request)
        .filter(status="submitted")
        .select_related("machine", "technician")
    )
    if not is_admin(request.user):
        qs = qs.filter(approver=request.user)
    return page(
        request, "pm_list.html", {"title": "Approval inbox", "tasks": qs, "is_approval": True, "nav": "approvals"}
    )


@app_view
def pm_detail(request, pk):
    obj = get_object_or_404(
        scoped(PMOccurrence, request.user).select_related("machine", "technician", "approver", "plan"), pk=pk
    )
    submit_form = SubmissionForm(
        initial={"version": obj.version, "completed_at": timezone.localtime().replace(second=0, microsecond=0)}
    )
    review_form = ReviewForm(initial={"version": obj.version})
    response_status = 200
    if request.method == "POST":
        action = request.POST.get("action")
        form = SubmissionForm(request.POST) if action == "submit" else ReviewForm(request.POST)
        if form.is_valid():
            try:
                if action == "submit":
                    submit_pm(request.user, obj.pk, **form.cleaned_data)
                elif action == "review":
                    review_pm(request.user, obj.pk, **form.cleaned_data)
                else:
                    raise ValidationError("Unknown action.")
                messages.success(request, "PM record updated.")
                return redirect("pm_detail", pk=pk)
            except ValidationError as exc:
                form_errors(form, exc)
                response_status = 409 if isinstance(exc, Conflict) else 200
        if action == "submit":
            submit_form = form
        else:
            review_form = form
    can_submit = (
        obj.technician_id == request.user.pk
        and obj.status in ("pending", "rejected")
        and Membership.objects.filter(user=request.user, plant=obj.plant, role="technician").exists()
    )
    can_review = (
        obj.approver_id == request.user.pk
        and obj.status == "submitted"
        and Membership.objects.filter(user=request.user, plant=obj.plant, role="approver").exists()
    )
    return page(
        request,
        "pm_detail.html",
        {
            "title": obj.task_name,
            "task": obj,
            "submissions": obj.submissions.select_related("submitted_by", "reviewed_by"),
            "submit_form": submit_form,
            "review_form": review_form,
            "can_submit": can_submit,
            "can_review": can_review,
            "nav": "pm",
        },
        response_status,
    )


@app_view
def breakdowns(request):
    qs = apply_filters(scoped(Breakdown, request.user), request).select_related("machine", "technician")
    state = request.GET.get("state", "open")
    if state == "open":
        qs = qs.exclude(status="closed")
    elif state == "closed":
        qs = qs.filter(status="closed")
    return page(
        request, "breakdowns.html", {"title": "Breakdown log", "incidents": qs, "state": state, "nav": "breakdowns"}
    )


@app_view
def breakdown_new(request):
    form = BreakdownForm(
        request.POST or None,
        user=request.user,
        initial={"occurred_at": timezone.localtime().replace(second=0, microsecond=0)},
    )
    if request.method == "POST" and form.is_valid():
        try:
            obj = save_breakdown(request.user, form.cleaned_data)
            messages.success(request, "Breakdown reported. Downtime is now being tracked.")
            return redirect("breakdown_detail", pk=obj.pk)
        except ValidationError as exc:
            form_errors(form, exc)
    return page(
        request,
        "form.html",
        {
            "title": "Report a breakdown",
            "subtitle": "Record when the machine stopped. The repair team can add the remaining details.",
            "form": form,
            "back_url": "/breakdowns/",
            "nav": "breakdowns",
        },
    )


@app_view
def breakdown_detail(request, pk):
    obj = get_object_or_404(
        scoped(Breakdown, request.user).select_related("machine", "reported_by", "technician"), pk=pk
    )
    initial = {
        key: getattr(obj, key)
        for key in ("version", "repair_start", "repair_end", "root_cause", "action_taken", "technician")
    }
    form = RepairForm(request.POST or None, initial=initial, user=request.user, plant_id=obj.plant_id)
    response_status = 200
    if request.method == "POST" and form.is_valid():
        try:
            data = dict(form.cleaned_data)
            version = data.pop("version")
            save_breakdown(request.user, data, pk, version)
            messages.success(request, "Repair details saved.")
            return redirect("breakdown_detail", pk=pk)
        except ValidationError as exc:
            form_errors(form, exc)
            response_status = 409 if isinstance(exc, Conflict) else 200
    can_repair = is_admin(request.user) or (
        obj.status != "closed"
        and Membership.objects.filter(user=request.user, plant=obj.plant, role="technician").exists()
    )
    return page(
        request,
        "breakdown_detail.html",
        {
            "title": f"Breakdown #{obj.pk:04d}",
            "incident": obj,
            "form": form,
            "can_repair": can_repair,
            "nav": "breakdowns",
        },
        response_status,
    )


@app_view
def runtime(request):
    records = apply_filters(scoped(RuntimeLog, request.user), request).select_related("machine", "entered_by")[:200]
    return page(request, "runtime.html", {"title": "Machine running hours", "records": records, "nav": "runtime"})


@app_view
def runtime_edit(request, pk=None):
    obj = get_object_or_404(scoped(RuntimeLog, request.user), pk=pk) if pk else None
    initial = (
        {"machine": obj.machine, "date": obj.date, "hours": obj.hours, "version": obj.version}
        if obj
        else {"date": timezone.localdate()}
    )
    form = RuntimeForm(request.POST or None, user=request.user, initial=initial)
    if obj:
        form.fields["machine"].disabled = True
    response_status = 200
    if request.method == "POST" and form.is_valid():
        try:
            data = dict(form.cleaned_data)
            version = data.pop("version", None)
            save_runtime(request.user, data, pk, version)
            messages.success(request, "Running hours saved.")
            return redirect("runtime")
        except ValidationError as exc:
            form_errors(form, exc)
            response_status = 409 if isinstance(exc, Conflict) else 200
    return page(
        request,
        "form.html",
        {
            "title": "Update running hours" if obj else "Record running hours",
            "subtitle": "Record actual daily operation so reliability reports reflect real machine use.",
            "form": form,
            "back_url": "/runtime/",
            "nav": "runtime",
        },
        response_status,
    )


@app_view
def notifications(request):
    records = Notification.objects.filter(recipient=request.user, plant_id__in=plant_ids(request.user)).select_related(
        "plant"
    )[:200]
    return page(
        request, "notifications.html", {"title": "Notifications", "notifications": records, "nav": "notifications"}
    )


@require_POST
@app_view
def notification_read(request, pk):
    obj = get_object_or_404(
        Notification.objects.filter(recipient=request.user, plant_id__in=plant_ids(request.user)), pk=pk
    )
    if not obj.read_at:
        obj.read_at = timezone.now()
        obj.save(update_fields=["read_at"])
    return redirect("notifications")
