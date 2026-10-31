from django import forms
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.utils import timezone

from .access import scoped_machines
from .models import User, Plant, Department, Membership, Machine, PMPlan, PMOccurrence, Breakdown, RuntimeLog
from .validation import validate_commissioning, validate_schedule


class Styled:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.HiddenInput):
                continue
            field.widget.attrs["class"] = (
                "form-check-input"
                if isinstance(field.widget, forms.CheckboxInput)
                else "form-select"
                if isinstance(field.widget, forms.Select)
                else "form-control"
            )
            if isinstance(field.widget, forms.Textarea):
                field.widget.attrs["rows"] = 4


class LoginForm(Styled, AuthenticationForm):
    username = forms.CharField(
        label="User ID", widget=forms.TextInput(attrs={"autocomplete": "username", "autofocus": True})
    )


class ChangePasswordForm(Styled, PasswordChangeForm):
    pass


class VersionForm(Styled, forms.ModelForm):
    version = forms.IntegerField(widget=forms.HiddenInput, required=False, initial=0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.initial["version"] = self.instance.version if self.instance.pk else 0


class PlantForm(VersionForm):
    class Meta:
        model = Plant
        fields = ["code", "name", "active"]


class DepartmentForm(VersionForm):
    class Meta:
        model = Department
        fields = ["plant", "code", "name"]

    def clean(self):
        data = super().clean()
        if (
            self.instance.pk
            and "plant" in self.changed_data
            and Machine.objects.filter(department=self.instance).exists()
        ):
            raise ValidationError("A department with machines cannot move between plants.")
        return data


class MachineForm(VersionForm):
    class Meta:
        model = Machine
        fields = ["plant", "department", "code", "name", "tonnage", "commissioned_on", "active"]
        widgets = {"commissioned_on": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def clean(self):
        data = super().clean()
        if data.get("department") and data.get("plant") and data["department"].plant_id != data["plant"].pk:
            self.add_error("department", "Select a department belonging to the selected plant.")
        if data.get("commissioned_on"):
            try:
                validate_commissioning(data["commissioned_on"])
            except ValidationError as exc:
                self.add_error("commissioned_on", exc)
        if self.instance.pk:
            history = any(
                model.objects.filter(machine=self.instance).exists() for model in (PMOccurrence, Breakdown, RuntimeLog)
            )
            if history and set(self.changed_data) & {"plant", "department", "commissioned_on"}:
                raise ValidationError(
                    "Location and commissioning date are fixed once history exists. Archive this machine and create a new entry for a transfer."
                )
            if PMPlan.objects.filter(machine=self.instance, active=True).exists() and set(self.changed_data) & {
                "plant",
                "department",
            }:
                raise ValidationError("Archive the machine’s active PM plans before changing its location.")
        return data


class PlanForm(VersionForm):
    class Meta:
        model = PMPlan
        fields = [
            "machine",
            "name",
            "instructions",
            "first_due",
            "interval",
            "unit",
            "technician",
            "approver",
            "active",
        ]
        widgets = {"first_due": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def clean(self):
        data = super().clean()
        machine = data.get("machine")
        if machine:
            for field, role in [("technician", "technician"), ("approver", "approver")]:
                user = data.get(field)
                if user and (
                    not user.is_active
                    or not Membership.objects.filter(user=user, plant=machine.plant, role=role).exists()
                ):
                    self.add_error(field, f"Select an active {role} assigned to {machine.plant.name}.")
            if data.get("first_due"):
                try:
                    validate_schedule(data["first_due"], machine.commissioned_on)
                except ValidationError as exc:
                    self.add_error("first_due", exc)
        if self.instance.pk:
            if "machine" in self.changed_data:
                raise ValidationError("Create a new plan to change the machine.")
            if set(self.changed_data) & {"first_due", "interval", "unit"}:
                latest = self.instance.occurrences.order_by("-due").first()
                if latest and data.get("first_due") and data["first_due"] <= max(latest.due, timezone.localdate()):
                    raise ValidationError(
                        "For a schedule change, set the first due date after today and all existing occurrences. Existing work stays unchanged."
                    )
        return data


class UserForm(VersionForm):
    temporary_password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        help_text="Required for a new user. They must change this password at first login.",
    )

    class Meta:
        model = User
        fields = ["username", "first_name", "last_name", "is_active", "is_superuser"]
        labels = {"username": "User ID", "is_superuser": "Global administrator"}

    def clean_temporary_password(self):
        password = self.cleaned_data.get("temporary_password", "")
        if not self.instance.pk and not password:
            raise ValidationError("Set an initial password.")
        if self.instance.pk and password:
            raise ValidationError("Use the dedicated Reset password action to change an existing password.")
        if password:
            candidate = User(username=self.data.get("username", ""), first_name=self.data.get("first_name", ""))
            validate_password(password, candidate)
        return password


class MembershipForm(VersionForm):
    class Meta:
        model = Membership
        fields = ["user", "plant", "role"]

    def clean(self):
        data = super().clean()
        if self.instance.pk and self.changed_data:
            original = Membership.objects.get(pk=self.instance.pk)
            if original.role in ("technician", "approver"):
                field = f"{original.role}_id"
                has_plans = PMPlan.objects.filter(
                    machine__plant=original.plant, active=True, **{field: original.user_id}
                ).exists()
                has_work = (
                    PMOccurrence.objects.filter(plant=original.plant, **{field: original.user_id})
                    .exclude(status="approved")
                    .exists()
                )
                if has_plans or has_work:
                    raise ValidationError(
                        "Reassign this user’s active plans and unresolved PM tasks before changing their plant role."
                    )
        return data


class ResetPasswordForm(Styled, forms.Form):
    new_password = forms.CharField(
        label="Temporary password", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"})
    )

    def __init__(self, *args, target_user=None, **kwargs):
        self.target_user = target_user
        super().__init__(*args, **kwargs)

    def clean_new_password(self):
        value = self.cleaned_data["new_password"]
        validate_password(value, self.target_user)
        return value


class SubmissionForm(Styled, forms.Form):
    version = forms.IntegerField(widget=forms.HiddenInput)
    completed_at = forms.DateTimeField(
        label="Completed at (IST)",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
    notes = forms.CharField(label="Work completed", widget=forms.Textarea)


class ReviewForm(Styled, forms.Form):
    version = forms.IntegerField(widget=forms.HiddenInput)
    decision = forms.ChoiceField(choices=[("approve", "Approve completion"), ("reject", "Return for correction")])
    reason = forms.CharField(required=False, label="Review notes / rejection reason", widget=forms.Textarea)


class BreakdownForm(Styled, forms.Form):
    machine = forms.ModelChoiceField(queryset=Machine.objects.none())
    occurred_at = forms.DateTimeField(
        label="Breakdown occurred at (IST)",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
    description = forms.CharField(widget=forms.Textarea)
    repair_start = forms.DateTimeField(
        required=False,
        label="Repair started at (IST, optional for historical entry)",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
    repair_end = forms.DateTimeField(
        required=False,
        label="Machine restored at (IST, optional for historical entry)",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
    root_cause = forms.CharField(required=False, widget=forms.Textarea)
    action_taken = forms.CharField(required=False, widget=forms.Textarea)
    technician = forms.ModelChoiceField(required=False, queryset=User.objects.none())

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        qs = scoped_machines(user).filter(active=True, plant__active=True)
        if not user.is_superuser:
            qs = qs.filter(plant__membership__user=user, plant__membership__role__in=["operator", "technician"])
        self.fields["machine"].queryset = qs
        if user.is_superuser:
            self.fields["technician"].queryset = User.objects.filter(
                is_active=True, memberships__role="technician"
            ).distinct()
        else:
            self.fields.pop("technician")
            if not Membership.objects.filter(user=user, role="technician").exists():
                for key in ("repair_start", "repair_end", "root_cause", "action_taken"):
                    self.fields.pop(key)


class RepairForm(Styled, forms.Form):
    version = forms.IntegerField(widget=forms.HiddenInput)
    repair_start = forms.DateTimeField(
        required=False,
        label="Repair started at (IST)",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
    repair_end = forms.DateTimeField(
        required=False,
        label="Repair finished / machine restored at (IST)",
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M"),
    )
    root_cause = forms.CharField(required=False, widget=forms.Textarea)
    action_taken = forms.CharField(required=False, widget=forms.Textarea)
    technician = forms.ModelChoiceField(
        required=False, queryset=User.objects.none(), help_text="Required when an administrator records a repair."
    )

    def __init__(self, *args, user=None, plant_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        if user and user.is_superuser:
            self.fields["technician"].queryset = User.objects.filter(
                is_active=True, memberships__plant_id=plant_id, memberships__role="technician"
            )
        else:
            self.fields.pop("technician")


class RuntimeForm(Styled, forms.Form):
    version = forms.IntegerField(widget=forms.HiddenInput, required=False, initial=0)
    machine = forms.ModelChoiceField(queryset=Machine.objects.none())
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"))
    hours = forms.DecimalField(
        min_value=0,
        max_value=24,
        max_digits=5,
        decimal_places=2,
        help_text="Actual operating hours. Enter 0 for a non-working day.",
    )

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["machine"].queryset = scoped_machines(user)
        if not user.is_superuser:
            self.fields["machine"].queryset = self.fields["machine"].queryset.filter(
                plant__membership__user=user, plant__membership__role__in=["operator", "technician"]
            )
