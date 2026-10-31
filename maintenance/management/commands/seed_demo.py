import os
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from maintenance.models import User, Plant, Department, Membership, Machine, PMPlan, PMOccurrence, RuntimeLog
from maintenance.scheduling import reconcile
from maintenance.services import submit_pm, review_pm, save_breakdown, record_fields, audit


class Command(BaseCommand):
    help = "Seed fictional two-plant demonstration data once. Requires DEMO_MODE=1 and DEMO_PASSWORD."

    @transaction.atomic
    def handle(self, *args, **options):
        if not settings.DEMO_MODE:
            raise CommandError("Demo seeding is disabled. Set DEMO_MODE=1 only for a demonstration database.")
        if Plant.objects.filter(code="DEMO-NORTH").exists() and Plant.objects.filter(code="DEMO-SOUTH").exists():
            self.stdout.write("Demo already seeded; existing data and passwords unchanged.")
            return
        if Plant.objects.exists() or Machine.objects.exists():
            raise CommandError("Demo seed requires an empty plant directory; existing records were not changed.")
        password = os.environ.get("DEMO_PASSWORD", "")
        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError("Set a strong DEMO_PASSWORD before seeding.") from exc
        today = timezone.localdate()
        now = timezone.now()
        machines = [
            ("HP-101", "Hydraulic press", 150),
            ("IM-102", "Injection moulding machine", 250),
            ("PP-103", "Pneumatic press", 80),
            ("HP-104", "Hydraulic press line 2", 200),
        ]
        for index, (code, name, prefix) in enumerate(
            [("DEMO-NORTH", "North Works", "north"), ("DEMO-SOUTH", "South Works", "south")]
        ):
            plant = Plant.objects.create(code=code, name=name)
            pressing = Department.objects.create(plant=plant, code="PRESS", name="Press shop")
            moulding = Department.objects.create(plant=plant, code="MOULD", name="Moulding")
            people = {}
            for role, first, last in [
                ("operator", "Aarav" if not index else "Meera", "Sharma"),
                ("technician", "Rohan" if not index else "Kavya", "Singh"),
                ("approver", "Priya" if not index else "Arjun", "Verma"),
            ]:
                suffix = "tech" if role == "technician" else role
                user = User.objects.create_user(
                    username=f"{prefix}.{suffix}",
                    password=password,
                    first_name=first,
                    last_name=last,
                    must_change_password=True,
                )
                Membership.objects.create(user=user, plant=plant, role=role)
                people[role] = user
            for machine_index, (machine_code, machine_name, tonnes) in enumerate(machines):
                machine = Machine.objects.create(
                    plant=plant,
                    department=moulding if machine_index == 1 else pressing,
                    code=machine_code.replace("1", "2", 1) if index else machine_code,
                    name=machine_name,
                    tonnage=tonnes,
                    commissioned_on=today - timedelta(days=365),
                )
                PMPlan.objects.create(
                    machine=machine,
                    name="Weekly safety & lubrication",
                    instructions="Inspect guards, emergency stops, oil levels and lubrication points. Record any defects.",
                    first_due=today - timedelta(days=21 - machine_index),
                    interval=1,
                    unit="weeks",
                    technician=people["technician"],
                    approver=people["approver"],
                )
                PMPlan.objects.create(
                    machine=machine,
                    name="Monthly preventive service",
                    instructions="Check hydraulic lines, seals, alignment and electrical connections. Clean filters and verify pressure.",
                    first_due=today + timedelta(days=machine_index + 1),
                    interval=1,
                    unit="months",
                    technician=people["technician"],
                    approver=people["approver"],
                )
                for offset in range(30, 0, -1):
                    day = today - timedelta(days=offset)
                    RuntimeLog.objects.create(
                        **record_fields(machine),
                        date=day,
                        hours=Decimal("0") if day.weekday() == 6 else Decimal(8 + machine_index),
                        entered_by=people["operator"],
                    )
                past = now - timedelta(days=9 + machine_index)
                save_breakdown(
                    people["technician"],
                    {
                        "machine": machine,
                        "occurred_at": past,
                        "description": "Pressure fluctuation during operation",
                        "repair_start": past + timedelta(minutes=30),
                        "repair_end": past + timedelta(hours=2 + machine_index),
                        "root_cause": "Worn hydraulic seal",
                        "action_taken": "Replaced seal; verified pressure under load.",
                    },
                )
                if machine_index == 0:
                    save_breakdown(
                        people["technician"],
                        {
                            "machine": machine,
                            "occurred_at": now - timedelta(hours=3 + index),
                            "description": "Oil leakage at the main cylinder",
                            "repair_start": now - timedelta(hours=2),
                            "root_cause": "Inspecting cylinder seal",
                            "action_taken": "Machine isolated; replacement seal being fitted.",
                        },
                    )
            reconcile(people["technician"])
            tasks = list(PMOccurrence.objects.filter(plant=plant, due__lt=today).order_by("due", "pk"))
            for number, task in enumerate(tasks):
                if number == len(tasks) - 1:
                    continue  # One overdue task per plant for the demonstration.
                completed = timezone.make_aware(datetime.combine(task.due, time(16)))
                submit_pm(
                    people["technician"],
                    task.pk,
                    1,
                    completed,
                    "Safety checks completed. Lubrication topped up; no abnormal noise or vibration.",
                )
                if number != len(tasks) - 2:
                    review_pm(people["approver"], task.pk, 2, "approve", "Checklist and machine condition verified.")
            audit(people["approver"], plant, "demo.plant_seeded", plant_id=plant.pk)
        self.stdout.write(
            "Demo seeded: 2 plants, 8 machines, 6 staff accounts. Temporary passwords must be changed on login."
        )
