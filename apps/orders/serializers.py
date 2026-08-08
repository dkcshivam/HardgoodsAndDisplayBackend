from django.db import transaction
from rest_framework import serializers

from .models import Carton, CartonContent, Order, OrderLine


class ShippingAddressSerializer(serializers.Serializer):
    """Flat columns on Order, nested here because that is the form's shape."""

    country = serializers.CharField(max_length=2, default="US")
    line1 = serializers.CharField(max_length=180, allow_blank=True, required=False)
    line2 = serializers.CharField(max_length=180, allow_blank=True, required=False)
    city = serializers.CharField(max_length=80, allow_blank=True, required=False)
    state = serializers.CharField(max_length=80, allow_blank=True, required=False)
    postal_code = serializers.CharField(max_length=20, allow_blank=True, required=False)


class OrderLineSerializer(serializers.ModelSerializer):
    product_style_no = serializers.CharField(source="product.style_no", read_only=True)
    product_description = serializers.CharField(
        source="product.description", read_only=True
    )

    class Meta:
        model = OrderLine
        fields = [
            "id",
            "product",
            "product_style_no",
            "product_description",
            "color",
            "quantity",
        ]


class CartonContentSerializer(serializers.ModelSerializer):
    product_style_no = serializers.CharField(source="product.style_no", read_only=True)
    part_name = serializers.CharField(source="part.name", default=None, read_only=True)

    class Meta:
        model = CartonContent
        fields = [
            "id",
            "product",
            "product_style_no",
            "part",
            "part_name",
            "description",
            "quantity",
            "unit",
            "net_weight_kg",
        ]


class CartonSerializer(serializers.ModelSerializer):
    contents = CartonContentSerializer(many=True)
    cbm = serializers.DecimalField(max_digits=12, decimal_places=4, read_only=True)
    net_weight_kg = serializers.DecimalField(
        max_digits=12, decimal_places=3, read_only=True
    )

    class Meta:
        model = Carton
        fields = [
            "id",
            "carton_no",
            "length_in",
            "width_in",
            "height_in",
            "net_weight_kg",
            "gross_weight_kg",
            "cbm",
            "sort_order",
            "contents",
        ]


class OrderSerializer(serializers.ModelSerializer):
    shipping_address = serializers.SerializerMethodField()
    merchant_name = serializers.CharField(source="merchant.name", read_only=True)
    lines = OrderLineSerializer(many=True, required=False)
    carton_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Order
        fields = [
            "id",
            "number",
            "name",
            "merchant",
            "merchant_name",
            "buyer_name",
            "shipping_address",
            "status",
            "lines",
            "carton_count",
            "created_at",
        ]
        read_only_fields = ["number", "status"]

    def get_shipping_address(self, obj) -> dict:
        return {
            "country": obj.ship_country,
            "line1": obj.ship_line1,
            "line2": obj.ship_line2,
            "city": obj.ship_city,
            "state": obj.ship_state,
            "postal_code": obj.ship_postal_code,
        }

    def to_internal_value(self, data):
        address = data.get("shipping_address")
        validated = super().to_internal_value(data)
        if isinstance(address, dict):
            nested = ShippingAddressSerializer(data=address)
            nested.is_valid(raise_exception=True)
            for key, value in nested.validated_data.items():
                validated[f"ship_{key}"] = value
        return validated

    @transaction.atomic
    def create(self, validated_data):
        lines_data = validated_data.pop("lines", [])
        order = Order.objects.create(**validated_data)
        self._write_lines(order, lines_data)
        return order

    @transaction.atomic
    def update(self, instance, validated_data):
        lines_data = validated_data.pop("lines", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if lines_data is not None:
            instance.lines.all().delete()
            self._write_lines(instance, lines_data)

        return instance

    @staticmethod
    def _write_lines(order, lines_data):
        for line in lines_data:
            line.pop("id", None)
            OrderLine.objects.create(order=order, **line)


# ── Packing workspace ────────────────────────────────────────────────


class ReconciliationSerializer(serializers.Serializer):
    product = serializers.IntegerField()
    style_no = serializers.CharField()
    ordered = serializers.IntegerField()
    packed = serializers.IntegerField()
    is_matched = serializers.BooleanField()


class BlockerSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    carton_id = serializers.IntegerField(allow_null=True)


class PackingPlanSerializer(serializers.Serializer):
    order = serializers.IntegerField()
    cartons = CartonSerializer(many=True)
    reconciliation = ReconciliationSerializer(many=True)
    blockers = BlockerSerializer(many=True)
    carton_count = serializers.IntegerField()
    total_quantity = serializers.IntegerField()
    total_gross_weight_kg = serializers.DecimalField(max_digits=12, decimal_places=3)
    total_cbm = serializers.DecimalField(max_digits=12, decimal_places=4)
    can_save = serializers.BooleanField()


class SaveCartonsSerializer(serializers.Serializer):
    """
    The table sends its whole contents on save. Replacing every carton in one
    transaction keeps the stored plan identical to the screen.
    """

    cartons = CartonSerializer(many=True)

    def validate_cartons(self, cartons):
        """
        The database also refuses duplicates, but as an IntegrityError — a 500
        with no useful message. Checking first gives a readable blocker.
        """
        seen: dict[str, int] = {}
        errors = []

        for index, carton in enumerate(cartons, start=1):
            number = (carton.get("carton_no") or "").strip()
            if not number:
                errors.append(f"Row {index} is missing a carton number.")
                continue
            seen[number] = seen.get(number, 0) + 1

        errors.extend(
            f"Carton number “{number}” is used {count} times."
            for number, count in seen.items()
            if count > 1
        )

        if errors:
            raise serializers.ValidationError(errors)

        return cartons
