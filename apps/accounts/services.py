from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from rest_framework.exceptions import ValidationError

from .models import Role, role_of

User = get_user_model()

ADMINS = Q(is_superuser=True) | Q(profile__role=Role.ADMIN)


def change_password(user, password: str) -> None:
    # The tokens carry a hash of the old password (CHECK_REVOKE_TOKEN), so
    # every session this user has, this one included, ends here.
    user.set_password(password)
    user.save(update_fields=["password"])


@transaction.atomic
def create_user(data: dict):
    role = data.pop("role", Role.MERCHANT)
    password = data.pop("password")
    user = User(**data)
    user.set_password(password)
    user.save()  # the receiver gives it a profile
    user.profile.role = role
    user.profile.save(update_fields=["role"])
    return user


@transaction.atomic
def update_user(actor, user, data: dict):
    check_change(actor, user, data)
    role = data.pop("role", None)
    password = data.pop("password", None)
    for field, value in data.items():
        setattr(user, field, value)
    if password:
        user.set_password(password)
    user.save()
    if role is not None and role != user.profile.role:
        user.profile.role = role
        user.profile.save(update_fields=["role"])
    return user


def check_change(actor, user, data: dict) -> None:
    if user.is_superuser and not actor.is_superuser:
        raise ValidationError(
            {"detail": "Only a superuser can change a superuser's account."}
        )

    role = data.get("role", role_of(user))
    is_active = data.get("is_active", user.is_active)

    if user.pk == actor.pk:
        if not is_active:
            raise ValidationError({"is_active": ["You cannot deactivate your own account."]})
        if role != role_of(user):
            raise ValidationError({"role": ["You cannot change your own role."]})

    if user.is_superuser and role != Role.ADMIN:
        raise ValidationError({"role": ["A superuser is always an admin."]})

    was_admin = user.is_active and role_of(user) == Role.ADMIN
    if was_admin and not (is_active and role == Role.ADMIN) and not _another_admin(user):
        raise ValidationError(
            {"detail": "This is the last active admin. Make someone else an admin first."}
        )


def _another_admin(user) -> bool:
    admins = User.objects.filter(ADMINS, is_active=True)
    # Lock every admin before counting, so two admins demoting each other at
    # the same moment queue up, and the second sees the first's change.
    list(
        User.objects.select_for_update()
        .filter(pk__in=list(admins.values_list("pk", flat=True)))
        .order_by("pk")
    )
    return admins.exclude(pk=user.pk).exists()
