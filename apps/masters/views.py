from rest_framework import viewsets

from .models import BoxType, Category, Merchant, ProductGroup
from .serializers import (
    BoxTypeSerializer,
    CategorySerializer,
    MerchantSerializer,
    ProductGroupSerializer,
)


class BoxTypeViewSet(viewsets.ModelViewSet):
    queryset = BoxType.objects.all()
    serializer_class = BoxTypeSerializer
    filterset_fields = ["is_active"]
    search_fields = ["code", "name"]
    ordering_fields = ["code", "name", "length_in"]


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    filterset_fields = ["is_active"]
    search_fields = ["name"]


class ProductGroupViewSet(viewsets.ModelViewSet):
    queryset = ProductGroup.objects.all()
    serializer_class = ProductGroupSerializer
    search_fields = ["name"]


class MerchantViewSet(viewsets.ModelViewSet):
    queryset = Merchant.objects.all()
    serializer_class = MerchantSerializer
    filterset_fields = ["is_active", "country"]
    search_fields = ["code", "name", "contact_name", "email"]
