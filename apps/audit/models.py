from django.apps import apps
from django.conf import settings
from django.db import models


class Action(models.TextChoices):
    CREATE = "create", "Created"
    UPDATE = "update", "Updated"
    DELETE = "delete", "Deleted"
    ADVANCE_STATUS = "advance_status", "Advanced status"
    SAVE_PACKING = "save_packing", "Saved packing"
    AUTO_PACK = "auto_pack", "Auto-packed"
    ADD_STEP = "add_step", "Added step"
    UPDATE_STEP = "update_step", "Changed step"
    DELETE_STEP = "delete_step", "Removed step"
    REPLICATE = "replicate", "Copied plan"
    LOGIN = "login", "Logged in"
    LOGOUT = "logout", "Logged out"


class AppendOnlyError(Exception):
    def __init__(self):
        super().__init__("Audit events are append-only: never changed, never deleted.")


class AuditEventQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AppendOnlyError()

    def delete(self):
        raise AppendOnlyError()


class AuditEvent(models.Model):
    """
    One write, as it happened. Refused an edit or a delete here, and again by
    a trigger in the database (migration 0002) for whatever goes around this.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    # Users are deactivated, never deleted, and an event must go on naming its
    # author: the admin refusing to delete one who has events is intended.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    # A snapshot, so a later rename does not rewrite who did what.
    actor_name = models.CharField(max_length=255, blank=True)
    action = models.CharField(max_length=20, choices=Action.choices)
    target_type = models.CharField(
        max_length=100, help_text="app_label.model, e.g. orders.order"
    )
    target_id = models.CharField(max_length=64)
    target_repr = models.CharField(
        max_length=255,
        blank=True,
        help_text="What the record was called at the time, e.g. HG-2026-0142.",
    )
    changes = models.JSONField(
        default=dict, blank=True, help_text="{field: [before, after]}"
    )

    objects = AuditEventQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["target_type", "target_id"], name="audit_event_target_idx")
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(action__in=Action.values),
                name="audit_event_action_is_known",
            )
        ]

    def __str__(self):
        return f"{self.actor_name or 'System'} · {self.get_action_display()} · {self.target_repr}"

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AppendOnlyError()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError()

    @property
    def target_label(self) -> str:
        try:
            model = apps.get_model(self.target_type)
        except (LookupError, ValueError):
            return self.target_type
        return str(model._meta.verbose_name).title()
