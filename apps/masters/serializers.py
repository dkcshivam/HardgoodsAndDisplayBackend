from rest_framework import serializers

from .models import Category, Merchant


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "is_active"]


class MerchantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Merchant
        fields = [
            "id",
            "code",
            "name",
            "contact_name",
            "email",
            "phone",
            "city",
            "country",
            "is_active",
        ]
