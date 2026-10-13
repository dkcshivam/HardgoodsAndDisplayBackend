from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class Role(models.TextChoices):
    ADMIN = "admin", "Admin"
    SENIOR_MERCHANT = "senior_merchant", "Senior Merchant"
    MERCHANT = "merchant", "Merchant"


class Profile(models.Model):
    """
    What the app knows about a user beyond Django's own fields. A one-to-one
    rather than a custom user model: auth_user already holds the production
    accounts, and Django cannot swap the user model under existing data.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.MERCHANT)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(role__in=Role.values), name="profile_role_is_known"
            )
        ]

    def __str__(self):
        return f"{self.user} · {self.get_role_display()}"


def default_role(user) -> Role:
    return Role.ADMIN if user.is_superuser else Role.MERCHANT


def role_of(user) -> Role | None:
    if not user.is_authenticated:
        return None
    # A superuser can already do anything in the Django admin; anything less
    # in the app would only invite them to work around it there.
    if user.is_superuser:
        return Role.ADMIN
    profile = getattr(user, "profile", None)
    # No profile means a user created around the ORM; give it the least.
    return Role(profile.role) if profile else Role.MERCHANT


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def give_new_user_a_profile(sender, instance, created, raw, **kwargs):
    # createsuperuser, the admin and the API all end in this save, so no
    # account is ever left without a role. Fixtures bring their own profiles.
    if created and not raw:
        Profile.objects.get_or_create(
            user=instance, defaults={"role": default_role(instance)}
        )
