from rest_framework import serializers

from .models import BoxType, Category, Merchant, ProductGroup


class BoxTypeSerializer(serializers.ModelSerializer):
    cbm = serializers.DecimalField(max_digits=12, decimal_places=4, read_only=True)

    class Meta:
        model = BoxType
        fields = [
            "id",
            "code",
            "name",
            "length_in",
            "width_in",
            "height_in",
            "max_weight_kg",
            "cbm",
            "is_active",
        ]


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ["id", "name", "is_active"]


class ProductGroupSerializer(serializers.ModelSerializer):
    product_count = serializers.IntegerField(source="products.count", read_only=True)

    class Meta:
        model = ProductGroup
        fields = ["id", "name", "remark", "product_count"]


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
