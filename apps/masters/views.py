from rest_framework import viewsets

from apps.audit.mixins import AuditedViewSetMixin

from .models import Category, Merchant, Store
from .serializers import CategorySerializer, MerchantSerializer, StoreSerializer


class CategoryViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    filterset_fields = ["is_active"]
    search_fields = ["name"]


class MerchantViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = Merchant.objects.all()
    serializer_class = MerchantSerializer
    filterset_fields = ["is_active", "country"]
    search_fields = ["code", "name", "contact_name", "email"]


class StoreViewSet(AuditedViewSetMixin, viewsets.ModelViewSet):
    queryset = Store.objects.all()
    serializer_class = StoreSerializer
    filterset_fields = ["is_active", "ship_country"]
    search_fields = ["name", "contact_name", "ship_city"]
