from django.db import transaction
from django.http import FileResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from . import services
from .exports import build_packing_list, packing_list_filename
from .models import (
    NEXT_STATUS,
    DisplayOrder,
    DisplayOrderStatus,
    DisplayProduct,
    DisplayProductImage,
    PackTemplate,
)
from .serializers import (
    AdjustmentSerializer,
    ApplyStepSerializer,
    DisplayCartonSerializer,
    DisplayOrderSerializer,
    DisplayProductImageSerializer,
    DisplayProductSerializer,
    PackingPlanSerializer,
    PackTemplateSerializer,
    RecountStepSerializer,
    ReplicatePlanSerializer,
    StoreRefSerializer,
)


class DisplayProductViewSet(viewsets.ModelViewSet):
    queryset = (
        DisplayProduct.objects.select_related("category")
        .prefetch_related("parts__images", "images")
        .all()
    )
    serializer_class = DisplayProductSerializer
    filterset_fields = ["status", "category", "is_multi_part"]
    search_fields = ["style_no", "style_name", "description"]
    ordering_fields = ["style_no", "created_at"]


class DisplayProductImageViewSet(viewsets.ModelViewSet):
    """
    Photos arrive one at a time as multipart, after their owner exists — a
    product or part has to have an id before a file can point at it.
    """

    queryset = DisplayProductImage.objects.select_related("product", "part")
    serializer_class = DisplayProductImageSerializer
    filterset_fields = ["product", "part"]

    def perform_create(self, serializer):
        owner = {
            key: value
            for key, value in serializer.validated_data.items()
            if key in {"product", "part"} and value
        }
        first = not DisplayProductImage.objects.filter(**owner).exists()
        # The first photo of an owner is its main one until told otherwise.
        serializer.save(
            is_main=serializer.validated_data.get("is_main", False) or first
        )

    def perform_destroy(self, instance):
        instance.image.delete(save=False)
        instance.delete()


class PackTemplateViewSet(viewsets.ModelViewSet):
    queryset = PackTemplate.objects.select_related("merchant").prefetch_related(
        "items__product", "items__part"
    )
    serializer_class = PackTemplateSerializer
    filterset_fields = ["is_library", "is_active", "merchant"]
    search_fields = ["code", "name"]
    ordering_fields = ["code", "created_at"]

    def perform_destroy(self, instance):
        # PackStep protects its template, so deleting one already packed would
        # surface as a 500. Say which orders hold it instead.
        orders = sorted(
            {step.order.number for step in instance.steps.select_related("order")}
        )
        if orders:
            raise ValidationError(
                {
                    "detail": (
                        f"{instance.code} is packed into {', '.join(orders)}. "
                        "Drop those steps first, or deactivate it instead."
                    )
                }
            )
        instance.delete()

    def update(self, request, *args, **kwargs):
        """
        Editing a design that is already packed replays the plan built from it,
        so the boxes end up holding what the design now says. Cartons snapshot
        their contents when a step is applied, so without the replay the two
        drift apart silently.
        """
        template = self.get_object()
        orders = services.orders_using(template)

        shipped = [
            order.number
            for order in orders
            if order.status == DisplayOrderStatus.SHIPPED
        ]
        if shipped:
            raise ValidationError(
                {
                    "detail": (
                        f"{template.code} is packed into {', '.join(shipped)}, "
                        "which has already shipped."
                    )
                }
            )

        # One order can be replayed; several cannot, because rewriting a design
        # would silently rebuild a plan somebody else is working to.
        if len(orders) > 1:
            raise ValidationError(
                {
                    "detail": (
                        f"{template.code} is packed into "
                        f"{', '.join(order.number for order in orders)}. Editing it "
                        "would rewrite all of them — copy it to a new code instead."
                    )
                }
            )

        before = self._contents_signature(template)

        with transaction.atomic():
            response = super().update(request, *args, **kwargs)
            # A rename leaves every box holding the same thing, and replaying
            # would renumber the tail's cartons for nothing.
            if orders and self._contents_signature(template) != before:
                response.data["adjustments"] = AdjustmentSerializer(
                    services.replay_template(orders[0], template), many=True
                ).data

        return response

    @staticmethod
    def _contents_signature(template):
        return sorted(template.items.values_list("product_id", "part_id", "quantity"))


class DisplayOrderViewSet(viewsets.ModelViewSet):
    queryset = (
        DisplayOrder.objects.select_related("merchant")
        .prefetch_related(
            "lines__product", "lines__store", "steps__template", "steps__store"
        )
        .all()
    )
    serializer_class = DisplayOrderSerializer
    filterset_fields = ["status", "merchant"]
    search_fields = ["number", "name", "buyer_name"]
    ordering_fields = ["created_at", "number"]

    def update(self, request, *args, **kwargs):
        """
        Lines can be added at any time; the serializer refuses to remove or
        reduce one that is already in cartons.
        """
        order = self.get_object()

        if order.status == DisplayOrderStatus.SHIPPED:
            return Response(
                {"detail": "This order has already shipped."},
                status=status.HTTP_409_CONFLICT,
            )

        before = self._demand_signature(order)
        response = super().update(request, *args, **kwargs)
        order.refresh_from_db()

        # A packed order that is asked for something new is not packed any
        # more — there is now demand no carton answers.
        if (
            order.status == DisplayOrderStatus.PACKED
            and self._demand_signature(order) != before
        ):
            order.status = DisplayOrderStatus.PACKING
            order.save(update_fields=["status", "updated_at"])
            response.data["status"] = order.status

        return response

    @staticmethod
    def _demand_signature(order):
        return sorted(order.lines.values_list("store_id", "product_id", "quantity"))

    # ── The packing workspace ────────────────────────────────────────

    @action(detail=True, methods=["get"])
    def packing(self, request, pk=None):
        """
        Steps, what is left, and which templates still fit. Deliberately not
        the cartons — a finished plan runs to thousands, and the screen works
        in steps.

        `?store=` narrows the plan to one store; without it the response
        carries the per-store overview and nothing store-specific.
        """
        order = self.get_object()
        return Response(self._plan(order, self._requested_store(request, order)))

    @action(detail=True, methods=["get"])
    def cartons(self, request, pk=None):
        """The boxes themselves, paginated — the drill-down from a step."""
        order = self.get_object()
        queryset = order.cartons.select_related(
            "step__template", "store"
        ).prefetch_related("contents__product", "contents__part")
        if (sequence := request.query_params.get("step")) is not None:
            queryset = queryset.filter(step__sequence=sequence)
        if (store := request.query_params.get("store")) is not None:
            queryset = queryset.filter(store_id=store)

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

        store = payload.validated_data["store"]
        if not order.lines.filter(store=store).exists():
            return Response(
                {"detail": f"Store {store.code} is not on this order."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            services.apply_step(
                order,
                payload.validated_data["template"],
                store,
                payload.validated_data.get("count"),
            )
        except services.PackingError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        self._advance_from_draft(order)
        return Response(self._plan(order, store.id))

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
                **self._plan(order, self._requested_store(request, order)),
                "adjustments": AdjustmentSerializer(adjustments, many=True).data,
            }
        )

    @action(detail=True, methods=["get"], url_path="packing-list")
    def packing_list(self, request, pk=None):
        """
        The plan as an Excel sheet, blocked by store. Available from the
        moment cartons exist — a draft list is what the floor works from
        while the order is still being packed.
        """
        order = self.get_object()

        if not order.cartons.exists():
            return Response(
                {"detail": "There are no cartons to list yet. Pack a store first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return FileResponse(
            build_packing_list(order),
            as_attachment=True,
            filename=packing_list_filename(order),
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )

    @action(detail=True, methods=["post"], url_path="replicate")
    def replicate(self, request, pk=None):
        """
        Copy one store's plan onto every other store with the same demand and
        nothing packed. The bulk move that makes a fifty-store order tractable.
        """
        order = self.get_object()

        if order.status == DisplayOrderStatus.SHIPPED:
            return Response(
                {"detail": "This order has already shipped."},
                status=status.HTTP_409_CONFLICT,
            )

        payload = ReplicatePlanSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        source = payload.validated_data["store"]

        try:
            copied = services.replicate_plan(order, source.id)
        except services.PackingError as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)

        self._advance_from_draft(order)
        return Response(
            {
                **self._plan(order, source.id),
                "replicated_to": StoreRefSerializer(
                    [
                        {
                            "store": s.id,
                            "store_code": s.code,
                            "store_name": s.name,
                        }
                        for s in copied
                    ],
                    many=True,
                ).data,
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
    def _plan(order, store_id=None):
        return PackingPlanSerializer(
            services.packing_summary(order, store_id)
        ).data

    def _requested_store(self, request, order):
        """
        Which store the caller is working in. Unknown or foreign ids fall back
        to the whole order rather than quietly showing another store's plan.
        """
        raw = request.query_params.get("store")
        if not raw:
            return None
        try:
            store_id = int(raw)
        except ValueError:
            return None
        return store_id if any(
            line.store_id == store_id for line in order.lines.all()
        ) else None
