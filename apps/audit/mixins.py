from . import services


class AuditedViewSetMixin:
    """
    Records each create, update and delete in the request's own transaction,
    so a request that fails leaves no event and one that succeeds always has
    one. `audit_related` names the collections a save writes alongside the
    record — parts, lines, items — so an edit to only those still shows.

    A viewset that writes its own way calls audit_create after the save, or
    wraps the write in audit_update / audit_delete.
    """

    audit_related: tuple[str, ...] = ()

    def perform_create(self, serializer):
        super().perform_create(serializer)
        self.audit_create(serializer.instance)

    def perform_update(self, serializer):
        with self.audit_update(serializer.instance):
            super().perform_update(serializer)

    def perform_destroy(self, instance):
        with self.audit_delete(instance):
            super().perform_destroy(instance)

    def audit_create(self, instance):
        services.record_create(self.request.user, instance, self.audit_related)

    def audit_update(self, instance):
        return services.recording_update(self.request.user, instance, self.audit_related)

    def audit_delete(self, instance):
        return services.recording_delete(self.request.user, instance, self.audit_related)
