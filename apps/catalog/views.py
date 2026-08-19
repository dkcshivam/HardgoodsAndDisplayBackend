from rest_framework import viewsets

from .models import Product, ProductImage
from .serializers import ProductImageSerializer, ProductListSerializer, ProductSerializer


class ProductViewSet(viewsets.ModelViewSet):
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
    ]
    ordering_fields = ["style_no", "style_name", "description", "created_at"]

    def get_serializer_class(self):
        if self.action == "list":
            return ProductListSerializer
        return ProductSerializer


class ProductImageViewSet(viewsets.ModelViewSet):
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
        serializer.save(is_main=serializer.validated_data.get("is_main", False) or first)

    def perform_destroy(self, instance):
        instance.image.delete(save=False)
        instance.delete()
