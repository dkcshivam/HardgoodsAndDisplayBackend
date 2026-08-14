from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from .models import Category, Merchant, Store


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


class StoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = Store
        fields = [
            "id",
            "name",
            "contact_name",
            "email",
            "phone",
            "ship_line1",
            "ship_line2",
            "ship_city",
            "ship_state",
            "ship_postal_code",
            "ship_country",
            "is_active",
        ]
        extra_kwargs = {
            "name": {
                "validators": [
                    UniqueValidator(
                        queryset=Store.objects.all(),
                        message="A store with that name already exists.",
                    )
                ]
            }
        }
