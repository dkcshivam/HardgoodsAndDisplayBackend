from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    # Read here, never written. What is done in this admin is not on the trail;
    # Django keeps its own history of that.
    list_display = ("created_at", "actor_name", "action", "target_type", "target_repr")
    list_filter = ("action", "target_type")
    search_fields = ("target_repr", "actor_name")
    search_help_text = "Search by record or by who made the change."
    date_hierarchy = "created_at"
    fields = (
        "created_at",
        "actor",
        "actor_name",
        "action",
        "target_type",
        "target_id",
        "target_repr",
        "changes",
    )
    readonly_fields = fields

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
