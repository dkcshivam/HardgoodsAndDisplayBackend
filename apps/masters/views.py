from rest_framework import viewsets

from .models import Category, Merchant
from .serializers import CategorySerializer, MerchantSerializer


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
