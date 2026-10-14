from datetime import datetime, time, timedelta

import django_filters
from django.utils import timezone
from rest_framework import viewsets

from apps.accounts.permissions import IsAdmin

from .models import AuditEvent
from .serializers import AuditEventSerializer


class AuditEventFilter(django_filters.FilterSet):
    # Whole days in the project's time zone, both ends included: the 12th is
    # the 12th as the desk lived it, not as UTC counts it.
    created_after = django_filters.DateFilter(method="filter_created_after")
    created_before = django_filters.DateFilter(method="filter_created_before")

    class Meta:
        model = AuditEvent
        fields = ["actor", "action", "target_type", "target_id"]

    def filter_created_after(self, queryset, name, day):
        return queryset.filter(created_at__gte=_midnight(day))

    def filter_created_before(self, queryset, name, day):
        return queryset.filter(created_at__lt=_midnight(day + timedelta(days=1)))


def _midnight(day):
    return timezone.make_aware(datetime.combine(day, time.min))


class AuditEventViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AuditEvent.objects.select_related("actor")
    serializer_class = AuditEventSerializer
    permission_classes = [IsAdmin]
    filterset_class = AuditEventFilter
    search_fields = ["target_repr", "actor_name"]
    ordering_fields = ["created_at"]
    ordering = ["-created_at", "-id"]
