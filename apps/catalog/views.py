from django.db.models import Q
from rest_framework import viewsets

from apps.audit.mixins import AuditedViewSetMixin
from apps.common.deletion import delete_with_photos, refuse_if_used

from .models import Product, ProductImage
from .serializers import (
    ProductImageSerializer,
    ProductListSerializer,
    ProductSerializer,
)


class ProductViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    """List returns a light shape so the table loads fast; detail returns all."""

    queryset = (
        Product.objects.select_related("category")
        .prefetch_related("parts__images", "images")
        .all()
    )
    filterset_fields = ["status", "category", "is_multi_part"]
    search_fields = [
        "style_no",
        "style_name",
        "description",
        "customs_description",
        "hsn_code",
        "hts_code",
    ]
    ordering_fields = ["style_no", "style_name", "description", "created_at"]
    audit_related = ("parts",)

    def get_serializer_class(self):
        if self.action == "list":
            return ProductListSerializer
        return ProductSerializer

    def perform_destroy(self, instance):
        refuse_if_used(
            instance,
            orders=[
                *instance.order_lines.values_list("order__number", flat=True),
                *instance.carton_contents.values_list(
                    "carton__order__number", flat=True
                ),
            ],
        )
        photos = ProductImage.objects.filter(
            Q(product=instance) | Q(part__product=instance)
        )
        with self.audit_delete(instance):
            delete_with_photos(instance, photos)


class ProductImageViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    """
    Photos arrive one at a time as multipart, after their owner exists — a
    product or part has to have an id before a file can point at it.
    """

    queryset = ProductImage.objects.select_related("product", "part")
    serializer_class = ProductImageSerializer
    filterset_fields = ["product", "part"]

    def perform_create(self, serializer):
        owner = {
            key: value
            for key, value in serializer.validated_data.items()
            if key in {"product", "part"} and value
        }
        first = not ProductImage.objects.filter(**owner).exists()
        # The first photo of an owner is its main one until told otherwise.
        serializer.save(
            is_main=serializer.validated_data.get("is_main", False) or first
        )
        self.audit_create(serializer.instance)

    def perform_destroy(self, instance):
        with self.audit_delete(instance):
            instance.image.delete(save=False)
            instance.delete()
