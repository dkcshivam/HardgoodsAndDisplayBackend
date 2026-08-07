from rest_framework import viewsets

from .models import Product
from .serializers import ProductListSerializer, ProductSerializer


class ProductViewSet(viewsets.ModelViewSet):
    """List returns a light shape so the table loads fast; detail returns all."""

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
