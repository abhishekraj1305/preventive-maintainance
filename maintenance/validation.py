from datetime import date, timedelta
from django.core.exceptions import ValidationError
from django.utils import timezone


def validate_commissioning(value):
    if not date(1900, 1, 1) <= value <= timezone.localdate():
        raise ValidationError("Commissioning date must be between 1 January 1900 and today.")


def validate_schedule(first_due, commissioned_on):
    today = timezone.localdate()
    if not today - timedelta(days=3660) <= first_due <= today + timedelta(days=3660):
        raise ValidationError(
            "The first tracked PM due date must be within ten years of today. Use the current schedule cycle for older machines."
        )
    if first_due < commissioned_on:
        raise ValidationError("First PM due date cannot precede commissioning.")
