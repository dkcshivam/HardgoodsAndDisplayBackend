from rest_framework import viewsets

from .models import Category, Merchant, Store
from .serializers import CategorySerializer, MerchantSerializer, StoreSerializer


class CategoryViewSet(viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    filterset_fields = ["is_active"]
    search_fields = ["name"]


class MerchantViewSet(viewsets.ModelViewSet):
    queryset = Merchant.objects.all()
    serializer_class = MerchantSerializer
    filterset_fields = ["is_active", "country"]
    search_fields = ["code", "name", "contact_name", "email"]


class StoreViewSet(viewsets.ModelViewSet):
    queryset = Store.objects.select_related("merchant")
    serializer_class = StoreSerializer
    filterset_fields = ["is_active", "merchant", "ship_country"]
    search_fields = ["code", "name", "contact_name", "ship_city"]
