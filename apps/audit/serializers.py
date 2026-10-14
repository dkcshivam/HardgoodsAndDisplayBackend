from rest_framework import serializers

from .models import AuditEvent


class AuditEventSerializer(serializers.ModelSerializer):
    action_label = serializers.CharField(source="get_action_display", read_only=True)
    target_label = serializers.CharField(read_only=True)

    class Meta:
        model = AuditEvent
        fields = [
            "id",
            "created_at",
            "actor",
            "actor_name",
            "action",
            "action_label",
            "target_type",
            "target_label",
            "target_id",
            "target_repr",
            "changes",
        ]
