from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q, F
from django.utils import timezone


class User(AbstractUser):
    must_change_password = models.BooleanField(default=True)
    version = models.PositiveIntegerField(default=1)


class Versioned(models.Model):
    version = models.PositiveIntegerField(default=1)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Plant(Versioned):
    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=120)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Department(Versioned):
    plant = models.ForeignKey(Plant, on_delete=models.PROTECT)
    code = models.CharField(max_length=30)
    name = models.CharField(max_length=120)

    class Meta:
        ordering = ["plant__name", "name"]
        constraints = [models.UniqueConstraint(fields=["plant", "code"], name="department_plant_code")]

    def __str__(self):
        return f"{self.plant.code} / {self.name}"


class Membership(Versioned):
    class Role(models.TextChoices):
        OPERATOR = "operator", "Operator"
        TECHNICIAN = "technician", "Technician"
        APPROVER = "approver", "Approver"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="memberships")
    plant = models.ForeignKey(Plant, on_delete=models.PROTECT)
    role = models.CharField(max_length=20, choices=Role.choices)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "plant"], name="one_role_per_plant")]


class Machine(Versioned):
    plant = models.ForeignKey(Plant, on_delete=models.PROTECT)
    department = models.ForeignKey(Department, on_delete=models.PROTECT)
    code = models.CharField("Machine ID", max_length=50)
    name = models.CharField(max_length=150)
    tonnage = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    active = models.BooleanField(default=True)
    commissioned_on = models.DateField(default=timezone.localdate)

    class Meta:
        ordering = ["plant__name", "code"]
        constraints = [models.UniqueConstraint(fields=["plant", "code"], name="machine_plant_code")]

    def __str__(self):
        return f"{self.code} · {self.name}"

    def snapshot(self):
        return {
            "code": self.code,
            "name": self.name,
            "tonnage": str(self.tonnage),
            "plant": self.plant.name,
            "department": self.department.name,
        }


class PMPlan(Versioned):
    class Unit(models.TextChoices):
        DAYS = "days", "Days"
        WEEKS = "weeks", "Weeks"
        MONTHS = "months", "Months"

    machine = models.ForeignKey(Machine, on_delete=models.PROTECT, related_name="plans")
    name = models.CharField(max_length=150)
    instructions = models.TextField(blank=True)
    first_due = models.DateField()
    interval = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1), MaxValueValidator(3650)])
    unit = models.CharField(max_length=10, choices=Unit.choices, default=Unit.MONTHS)
    technician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="assigned_plans")
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="review_plans")
    active = models.BooleanField(default=True)
    next_index = models.PositiveIntegerField(default=0, editable=False)

    class Meta:
        ordering = ["machine__code", "name"]
        constraints = [
            models.UniqueConstraint(fields=["machine", "name"], name="plan_machine_name"),
            models.CheckConstraint(condition=Q(interval__gte=1), name="positive_pm_interval"),
        ]

    def __str__(self):
        return f"{self.machine.code} / {self.name}"


class EventRecord(Versioned):
    machine = models.ForeignKey(Machine, on_delete=models.PROTECT)
    plant = models.ForeignKey(Plant, on_delete=models.PROTECT)
    department = models.ForeignKey(Department, on_delete=models.PROTECT)
    snapshot = models.JSONField(default=dict)

    class Meta:
        abstract = True


class PMOccurrence(EventRecord):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SUBMITTED = "submitted", "Awaiting approval"
        REJECTED = "rejected", "Rejected"
        APPROVED = "approved", "Approved"

    plan = models.ForeignKey(PMPlan, on_delete=models.PROTECT, related_name="occurrences")
    task_name = models.CharField(max_length=150)
    due = models.DateField(db_index=True)
    status = models.CharField(max_length=15, choices=Status.choices, default=Status.PENDING)
    technician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pm_tasks")
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="pm_reviews")
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["due", "machine__code", "task_name"]
        constraints = [models.UniqueConstraint(fields=["plan", "due"], name="one_pm_occurrence")]

    @property
    def deadline(self):
        # Exclusive deadline: midnight following the due date.
        return timezone.make_aware(datetime.combine(self.due + timedelta(days=1), time.min))

    @property
    def urgency(self):
        if self.status == self.Status.APPROVED:
            return "complete"
        today = timezone.localdate()
        if self.due < today:
            return "overdue"
        return "today" if self.due == today else "upcoming"

    def __str__(self):
        return f"{self.machine.code} / {self.task_name} / {self.due}"


class PMSubmission(models.Model):
    occurrence = models.ForeignKey(PMOccurrence, on_delete=models.PROTECT, related_name="submissions")
    submitted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    submitted_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField()
    notes = models.TextField()
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, related_name="+")
    reviewed_at = models.DateTimeField(null=True)
    decision = models.CharField(max_length=12, blank=True)
    reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-submitted_at", "-pk"]


class Breakdown(EventRecord):
    class Status(models.TextChoices):
        OPEN = "open", "Open"
        REPAIR = "repair", "In repair"
        CLOSED = "closed", "Closed"

    occurred_at = models.DateTimeField(db_index=True)
    description = models.TextField()
    repair_start = models.DateTimeField(null=True, blank=True)
    repair_end = models.DateTimeField(null=True, blank=True)
    root_cause = models.TextField(blank=True)
    action_taken = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.OPEN)
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    technician = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True, related_name="+"
    )

    class Meta:
        ordering = ["-occurred_at"]
        constraints = [
            models.UniqueConstraint(fields=["machine"], condition=~Q(status="closed"), name="one_open_breakdown"),
            models.CheckConstraint(
                condition=Q(repair_start__isnull=True) | Q(repair_start__gte=F("occurred_at")),
                name="repair_after_breakdown",
            ),
            models.CheckConstraint(
                condition=Q(repair_end__isnull=True) | Q(repair_end__gte=F("repair_start")), name="end_after_start"
            ),
        ]

    @property
    def downtime_hours(self):
        return max(0, ((self.repair_end or timezone.now()) - self.occurred_at).total_seconds() / 3600)

    @property
    def repair_hours(self):
        if self.repair_start and self.repair_end:
            return (self.repair_end - self.repair_start).total_seconds() / 3600
        return None


class RuntimeLog(EventRecord):
    date = models.DateField(db_index=True)
    hours = models.DecimalField(
        max_digits=5, decimal_places=2, validators=[MinValueValidator(0), MaxValueValidator(24)]
    )
    entered_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

    class Meta:
        ordering = ["-date", "machine__code"]
        constraints = [
            models.UniqueConstraint(fields=["machine", "date"], name="daily_runtime_unique"),
            models.CheckConstraint(
                condition=Q(hours__gte=Decimal("0")) & Q(hours__lte=Decimal("24")), name="runtime_0_to_24"
            ),
        ]


class Notification(models.Model):
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    plant = models.ForeignKey(Plant, on_delete=models.PROTECT)
    key = models.CharField(max_length=180)
    title = models.CharField(max_length=200)
    body = models.TextField()
    url = models.CharField(max_length=250)
    created_at = models.DateTimeField(default=timezone.now)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["recipient", "key"], name="notification_event_once")]


class AuditEvent(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True)
    plant = models.ForeignKey(Plant, on_delete=models.PROTECT, null=True)
    action = models.CharField(max_length=60)
    entity = models.CharField(max_length=80)
    object_id = models.PositiveBigIntegerField()
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]
