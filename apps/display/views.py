from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from . import services
from .models import (
    NEXT_STATUS,
    DisplayOrder,
    DisplayOrderStatus,
    DisplayProduct,
    PackTemplate,
)
from .serializers import (
    AdjustmentSerializer,
    ApplyStepSerializer,
    DisplayCartonSerializer,
    DisplayOrderSerializer,
    DisplayProductSerializer,
    PackingPlanSerializer,
    PackTemplateSerializer,
    RecountStepSerializer,
)


class DisplayProductViewSet(viewsets.ModelViewSet):
    queryset = DisplayProduct.objects.select_related("category").all()
    serializer_class = DisplayProductSerializer
    filterset_fields = ["status", "category"]
    search_fields = ["style_no", "description"]
    ordering_fields = ["style_no", "created_at"]


class PackTemplateViewSet(viewsets.ModelViewSet):
    queryset = PackTemplate.objects.select_related("merchant").prefetch_related(
        "items__product"
    )
    serializer_class = PackTemplateSerializer
    filterset_fields = ["is_library", "is_active", "merchant"]
    search_fields = ["code", "name"]
    ordering_fields = ["code", "created_at"]


class DisplayOrderViewSet(viewsets.ModelViewSet):
    queryset = (
        DisplayOrder.objects.select_related("merchant")
        .prefetch_related("lines__product", "steps__template")
        .all()
    )
    serializer_class = DisplayOrderSerializer
    filterset_fields = ["status", "merchant"]
    search_fields = ["number", "name", "buyer_name"]
    ordering_fields = ["created_at", "number"]

    # ── The packing workspace ────────────────────────────────────────

    @action(detail=True, methods=["get"])
    def packing(self, request, pk=None):
        """
        Steps, what is left, and which templates still fit. Deliberately not
        the cartons — a finished plan runs to thousands, and the screen works
        in steps.
        """
        return Response(self._plan(self.get_object()))

    @action(detail=True, methods=["get"])
    def cartons(self, request, pk=None):
        """The boxes themselves, paginated — the drill-down from a step."""
        order = self.get_object()
        queryset = order.cartons.select_related("step__template").prefetch_related(
            "contents__product"
        )
        if (sequence := request.query_params.get("step")) is not None:
            queryset = queryset.filter(step__sequence=sequence)

        page = self.paginate_queryset(queryset)
        serializer = DisplayCartonSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    # GET and POST share one url_path; two actions on the same path would
    # register two identical patterns and the first would shadow the second.
    @action(detail=True, methods=["post"])
    def steps(self, request, pk=None):
        """Apply a template. Without a count it applies as many times as it fits."""
        order = self.get_object()

        if order.status == DisplayOrderStatus.SHIPPED:
            return Response(
                {"detail": "This order has already shipped."},
                status=status.HTTP_409_CONFLICT,
            )

        payload = ApplyStepSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        try:
            services.apply_step(
                order,
                payload.validated_data["template"],
                payload.validated_data.get("count"),
            )
        except services.PackingError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        self._advance_from_draft(order)
        return Response(self._plan(order))

    @action(
        detail=True,
        methods=["patch", "delete"],
        url_path=r"steps/(?P<sequence>\d+)",
    )
    def step_detail(self, request, pk=None, sequence=None):
        """
        Re-count or drop a step, then replay everything after it. This is what
        makes the greedy loop recoverable: the fix for a bad tail is usually to
        change an early step, not to add another one.
        """
        order = self.get_object()

        if order.status == DisplayOrderStatus.SHIPPED:
            return Response(
                {"detail": "This order has already shipped."},
                status=status.HTTP_409_CONFLICT,
            )

        try:
            if request.method == "DELETE":
                adjustments = services.delete_step(order, int(sequence))
            else:
                payload = RecountStepSerializer(data=request.data)
                payload.is_valid(raise_exception=True)
                adjustments = services.recount_step(
                    order, int(sequence), payload.validated_data["count"]
                )
        except services.PackingError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                **self._plan(order),
                "adjustments": AdjustmentSerializer(adjustments, many=True).data,
            }
        )

    @action(detail=True, methods=["post"], url_path="advance-status")
    def advance_status(self, request, pk=None):
        order = self.get_object()
        next_status = NEXT_STATUS.get(DisplayOrderStatus(order.status))

        if next_status is None:
            return Response(
                {"detail": f"An order that is {order.status} cannot advance further."},
                status=status.HTTP_409_CONFLICT,
            )

        if next_status == DisplayOrderStatus.PACKED:
            blockers = services.find_blockers(order)
            if blockers or not order.cartons.exists():
                return Response(
                    {
                        "detail": "Resolve packing before marking this order packed.",
                        "blockers": [blocker.__dict__ for blocker in blockers],
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        order.status = next_status
        order.save(update_fields=["status", "updated_at"])
        return Response(DisplayOrderSerializer(order).data)

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _advance_from_draft(order):
        if order.status == DisplayOrderStatus.DRAFT:
            order.status = DisplayOrderStatus.PACKING
            order.save(update_fields=["status", "updated_at"])

    @staticmethod
    def _plan(order):
        return PackingPlanSerializer(services.packing_summary(order)).data
