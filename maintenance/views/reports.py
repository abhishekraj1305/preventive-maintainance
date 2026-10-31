from datetime import date, timedelta
import secrets
from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.http import require_POST

from maintenance.access import scoped_machines
from maintenance.reporting import build_report
from maintenance.excel import preview_import, commit_import, export_report, import_template
from maintenance.forms import Styled
from .common import app_view, admin_view, page, selected


class UploadForm(Styled, forms.Form):
    workbook = forms.FileField(label="Excel workbook (.xlsx)", widget=forms.FileInput(attrs={"accept": ".xlsx"}))


def report_period(request):
    today = timezone.localdate()
    preset = request.GET.get("period", "month")
    start = (
        today
        if preset == "day"
        else today - timedelta(days=today.weekday())
        if preset == "week"
        else today.replace(day=1)
    )
    end = today
    try:
        start = date.fromisoformat(request.GET["start"]) if request.GET.get("start") else start
        end = date.fromisoformat(request.GET["end"]) if request.GET.get("end") else end
        if start > end or (end - start).days > 3660:
            raise ValueError()
    except ValueError:
        messages.error(request, "Invalid date range. Showing the current month.")
        start, end = today.replace(day=1), today
    return start, end


def current_report(request):
    start, end = report_period(request)
    return build_report(
        request.user,
        start,
        end,
        selected(request, "plant"),
        selected(request, "department"),
        selected(request, "machine"),
    )


@app_view
def reports(request):
    report = current_report(request)
    return page(
        request,
        "reports.html",
        {
            "title": "Maintenance reports",
            "report": report,
            "machines": scoped_machines(request.user),
            "selected_machine": selected(request, "machine"),
            "querystring": request.GET.urlencode(),
            "nav": "reports",
        },
    )


def xlsx_response(content, name):
    response = HttpResponse(content, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="{name}.xlsx"'
    response["Cache-Control"] = "no-store"
    return response


@app_view
def reports_export(request):
    return xlsx_response(export_report(current_report(request)), "maintenance-report")


@admin_view
def excel_import(request):
    form = UploadForm(request.POST or None, request.FILES or None)
    preview = request.session.get("import_preview")
    if request.method == "POST" and form.is_valid():
        request.session.pop("import_preview", None)
        preview = None
        try:
            preview = preview_import(request.user, form.cleaned_data["workbook"])
            preview["preview_id"] = secrets.token_urlsafe(24)
            request.session["import_preview"] = preview
        except ValidationError as exc:
            for error in exc.messages:
                form.add_error("workbook", error)
    return page(
        request,
        "import.html",
        {"title": "Import machines & PM plans", "form": form, "preview": preview, "nav": "settings"},
    )


@require_POST
@admin_view
def excel_commit(request):
    preview = request.session.get("import_preview")
    if not preview:
        messages.error(request, "Upload a workbook and review its preview first.")
    elif not secrets.compare_digest(request.POST.get("preview_id", ""), preview.get("preview_id", "invalid")):
        messages.error(request, "This preview is no longer current. Review the latest workbook before confirming.")
    else:
        request.session.pop("import_preview", None)
        try:
            counts = commit_import(request.user, preview)
            messages.success(request, f"Imported {counts['machines']} machines and {counts['plans']} PM plans.")
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
    return redirect("excel_import")


@admin_view
def excel_template(request):
    return xlsx_response(import_template(), "machine-pm-import-template")
