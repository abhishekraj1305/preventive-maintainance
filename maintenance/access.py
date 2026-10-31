from django.core.exceptions import PermissionDenied
from .models import Plant, Membership, Machine


def is_admin(user):
    return user.is_authenticated and user.is_active and user.is_superuser


def plant_ids(user):
    if not user.is_authenticated or not user.is_active:
        return Plant.objects.none().values_list("pk", flat=True)
    if is_admin(user):
        return Plant.objects.values_list("pk", flat=True)
    return Membership.objects.filter(user=user).values_list("plant_id", flat=True)


def require_role(user, plant_id, roles, admin_ok=True):
    if admin_ok and is_admin(user):
        return
    if (
        not user.is_authenticated
        or not user.is_active
        or not Membership.objects.filter(user=user, plant_id=plant_id, role__in=roles).exists()
    ):
        raise PermissionDenied("Your role does not permit this action for this plant.")


def scoped_machines(user):
    return Machine.objects.filter(plant_id__in=plant_ids(user)).select_related("plant", "department")


def scoped(model, user):
    return model.objects.filter(plant_id__in=plant_ids(user))
