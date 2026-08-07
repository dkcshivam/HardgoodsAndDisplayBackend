from rest_framework import viewsets

from .models import Product
from .serializers import ProductListSerializer, ProductSerializer


class ProductViewSet(viewsets.ModelViewSet):
    """
    The catalogue of packing recipes.

    The list endpoint returns a light shape (no parts, no images) so the
    products table loads fast; detail returns everything.
    """

    queryset = (
        Product.objects.select_related("category", "product_group", "box_type")
        .prefetch_related("parts__box_type", "parts__images", "images")
        .all()
    )
    filterset_fields = ["status", "category", "product_group", "is_multi_part", "is_fragile"]
    search_fields = ["style_no", "description", "customs_description", "hsn_code"]
    ordering_fields = ["style_no", "description", "created_at"]

    def get_serializer_class(self):
        if self.action == "list":
            return ProductListSerializer
        return ProductSerializer
