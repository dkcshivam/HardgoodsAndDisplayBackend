from rest_framework import serializers

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
    merchant_name = serializers.CharField(source="merchant.name", read_only=True)

    class Meta:
        model = Store
        fields = [
            "id",
            "merchant",
            "merchant_name",
            "code",
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
        # DRF's own unique-together check reports against non_field_errors,
        # which a form cannot highlight. validate() below says it on `code`.
        validators = []

    def validate(self, attrs):
        merchant = attrs.get("merchant", getattr(self.instance, "merchant", None))
        code = attrs.get("code", getattr(self.instance, "code", None))
        clash = Store.objects.filter(merchant=merchant, code=code)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(
                {"code": "This merchant already has a store with that code."}
            )
        return attrs
