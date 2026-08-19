from django.db import transaction
from django.http import FileResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from . import services
from .exports import (
    build_invoice,
    build_packing_list,
    invoice_filename,
    packing_list_filename,
)
from .models import Carton, CartonContent, NEXT_STATUS, Order, OrderStatus
from .serializers import (
    OrderSerializer,
    PackingPlanSerializer,
    SaveCartonsSerializer,
)


class OrderViewSet(viewsets.ModelViewSet):
    queryset = (
        Order.objects.select_related("merchant")
        .prefetch_related("lines__product", "cartons__contents")
        .all()
    )
    serializer_class = OrderSerializer
    filterset_fields = ["status", "merchant"]
    search_fields = ["number", "name", "buyer_name"]
    ordering_fields = ["created_at", "number"]

    # ── Packing workspace ────────────────────────────────────────────

    # GET and PUT share one action: two actions on the same url_path would
    # register two identical URL patterns, and the first would shadow the second.
    @action(detail=True, methods=["get", "put"])
    def packing(self, request, pk=None):
        """Read the current plan, or replace it wholesale."""
        if request.method == "PUT":
            return self._save_packing(request)
        return Response(self._plan_payload(self.get_object()))

    @action(detail=True, methods=["post"], url_path="auto-pack")
    def auto_pack(self, request, pk=None):
        """Replace the plan with a proposal built from the products' recipes."""
        order = self.get_object()

        if order.status == OrderStatus.SHIPPED:
            return Response(
                {"detail": "This order has already shipped."},
                status=status.HTTP_409_CONFLICT,
            )

        plan = services.build_packing_plan(order)
        services.apply_packing_plan(order, plan)

        order.refresh_from_db()
        return Response(self._plan_payload(order))

    def _save_packing(self, request):
        """
        Replace the order's cartons with what the table holds. Rolls back on
        any blocker, so a plan with known problems can never be stored.
        """
        order = self.get_object()

        payload = SaveCartonsSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        with transaction.atomic():
            self._replace_cartons(order, payload.validated_data["cartons"])
            order.refresh_from_db()

            blockers = services.find_blockers(order)
            if blockers:
                transaction.set_rollback(True)
                return Response(
                    {
                        "detail": "Resolve the blockers before saving.",
                        "blockers": [blocker.__dict__ for blocker in blockers],
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if order.status == OrderStatus.DRAFT:
                order.status = OrderStatus.PACKING
                order.save(update_fields=["status", "updated_at"])

        order.refresh_from_db()
        return Response(self._plan_payload(order))

    @action(detail=True, methods=["get"], url_path="packing-list")
    def packing_list(self, request, pk=None):
        """
        The plan as an Excel sheet. Available from the moment cartons exist —
        a draft list is what the floor works from while the order is packed.
        """
        order = self.get_object()

        if not order.cartons.exists():
            return Response(
                {"detail": "There are no cartons to list yet. Run auto-pack first."},
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

    @action(detail=True, methods=["get"], url_path="invoice")
    def invoice(self, request, pk=None):
        """
        The commercial invoice. Billed on what is packed, so it needs cartons
        for the same reason the packing list does — and the two documents then
        carry the same quantity, which is the pair a broker checks first.
        """
        order = self.get_object()

        if not order.cartons.exists():
            return Response(
                {"detail": "There is nothing to invoice yet — pack the order first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return FileResponse(
            build_invoice(order),
            as_attachment=True,
            filename=invoice_filename(order),
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )

    @action(detail=True, methods=["post"], url_path="advance-status")
    def advance_status(self, request, pk=None):
        """
        One rung up: draft -> packing -> packed -> shipped. Reaching "packed"
        requires a clean plan — nothing is marked ready while the boxes and
        the order disagree.
        """
        order = self.get_object()
        next_status = NEXT_STATUS.get(OrderStatus(order.status))

        if next_status is None:
            return Response(
                {"detail": f"An order that is {order.status} cannot advance further."},
                status=status.HTTP_409_CONFLICT,
            )

        if next_status == OrderStatus.PACKED:
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
        return Response(OrderSerializer(order).data)

    # ── Helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _replace_cartons(order, cartons_data):
        order.cartons.all().delete()
        for index, carton_data in enumerate(cartons_data):
            contents = carton_data.pop("contents", [])
            carton_data.pop("id", None)
            carton_data.setdefault("sort_order", index)

            carton = Carton.objects.create(order=order, **carton_data)
            CartonContent.objects.bulk_create(
                [
                    CartonContent(carton=carton, **{k: v for k, v in content.items() if k != "id"})
                    for content in contents
                ]
            )

    @staticmethod
    def _plan_payload(order):
        summary = services.packing_summary(order)
        payload = {
            "order": order.id,
            "cartons": order.cartons.prefetch_related("contents").all(),
            **summary,
        }
        return PackingPlanSerializer(payload).data
