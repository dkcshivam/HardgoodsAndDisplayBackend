from django.db import transaction
from rest_framework import serializers

from apps.masters.models import Store

from .models import (
    DisplayCarton,
    DisplayCartonContent,
    DisplayOrder,
    DisplayOrderLine,
    DisplayProduct,
    DisplayProductPart,
    PackTemplate,
    PackTemplateItem,
)


class DisplayProductPartSerializer(serializers.ModelSerializer):
    # Kept on write so an edit can match a payload row to the part it edits;
    # without it every save would recreate the parts and orphan the template
    # items and carton contents pointing at them.
    id = serializers.IntegerField(required=False)
    unit_cbm = serializers.DecimalField(max_digits=12, decimal_places=4, read_only=True)

    class Meta:
        model = DisplayProductPart
        fields = [
            "id",
            "name",
            "description",
            "customs_description",
            "hsn_code",
            "product_weight_kg",
            "length_in",
            "width_in",
            "height_in",
            "unit_cbm",
            "sort_order",
        ]


class DisplayProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    unit_cbm = serializers.DecimalField(max_digits=12, decimal_places=4, read_only=True)
    parts = DisplayProductPartSerializer(many=True, required=False)

    class Meta:
        model = DisplayProduct
        fields = [
            "id",
            "style_no",
            "description",
            "category",
            "category_name",
            "customs_description",
            "hsn_code",
            "is_multi_part",
            "status",
            "product_weight_kg",
            "length_in",
            "width_in",
            "height_in",
            "unit_cbm",
            "parts",
            "created_at",
        ]

    def validate(self, attrs):
        is_multi_part = attrs.get(
            "is_multi_part",
            getattr(self.instance, "is_multi_part", False),
        )
        parts = attrs.get("parts")

        # The shape decides how this SKU is counted and packed, so orders
        # already planned under one shape would silently change meaning.
        if self.instance and is_multi_part != self.instance.is_multi_part:
            raise serializers.ValidationError(
                {
                    "is_multi_part": "How a product packs is fixed once it is saved. "
                    "Create a new style number for a different shape."
                }
            )

        if is_multi_part:
            own = [f for f in DisplayProduct.OWN_FIGURE_FIELDS if attrs.get(f) is not None]
            if own:
                raise serializers.ValidationError(
                    {
                        own[0]: "A multi-part product is never handled whole — "
                        "each part carries its own weight and size."
                    }
                )
            if parts is not None and len(parts) < 2:
                raise serializers.ValidationError(
                    {"parts": "A multi-part product needs at least two parts."}
                )
            if parts is None and self.instance is None:
                raise serializers.ValidationError(
                    {"parts": "A multi-part product needs at least two parts."}
                )
        elif parts:
            raise serializers.ValidationError(
                {"parts": "A single-piece product has no parts."}
            )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        parts = validated_data.pop("parts", [])
        product = DisplayProduct.objects.create(**validated_data)
        self._sync_parts(product, parts)
        return product

    @transaction.atomic
    def update(self, instance, validated_data):
        parts = validated_data.pop("parts", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if parts is not None:
            # The form always sends the complete list.
            self._sync_parts(instance, parts)

        return instance

    @staticmethod
    def _sync_parts(product, parts_data):
        """
        Match payload rows to existing parts by id and update them in place.
        Recreating them would break every template item aimed at a part.
        """
        existing = {part.id: part for part in product.parts.all()}
        kept = set()

        for index, data in enumerate(parts_data):
            part_id = data.pop("id", None)
            data.setdefault("sort_order", index)
            part = existing.get(part_id)

            if part is None:
                part = DisplayProductPart.objects.create(product=product, **data)
            else:
                for attr, value in data.items():
                    setattr(part, attr, value)
                part.save()

            kept.add(part.id)

        product.parts.exclude(id__in=kept).delete()


# ── Templates ────────────────────────────────────────────────────────


class PackTemplateItemSerializer(serializers.ModelSerializer):
    product_style_no = serializers.CharField(source="product.style_no", read_only=True)
    product_description = serializers.CharField(
        source="product.description", read_only=True
    )
    part_name = serializers.CharField(source="part.name", default="", read_only=True)

    class Meta:
        model = PackTemplateItem
        fields = [
            "id",
            "product",
            "product_style_no",
            "product_description",
            "part",
            "part_name",
            "quantity",
        ]

    def validate(self, attrs):
        product = attrs.get("product")
        part = attrs.get("part")

        if product is None:
            return attrs

        if product.is_multi_part and part is None:
            raise serializers.ValidationError(
                {
                    "part": f"{product.style_no} packs as parts — say which part "
                    "goes in this box."
                }
            )
        if not product.is_multi_part and part is not None:
            raise serializers.ValidationError(
                {"part": f"{product.style_no} is a single piece and has no parts."}
            )
        if part is not None and part.product_id != product.id:
            raise serializers.ValidationError(
                {"part": "That part belongs to a different product."}
            )

        return attrs


class PackTemplateSerializer(serializers.ModelSerializer):
    items = PackTemplateItemSerializer(many=True)
    merchant_name = serializers.CharField(source="merchant.name", read_only=True)
    cbm = serializers.DecimalField(max_digits=12, decimal_places=4, read_only=True)
    net_weight_kg = serializers.DecimalField(
        max_digits=12, decimal_places=3, read_only=True
    )
    gross_weight_kg = serializers.DecimalField(
        max_digits=12, decimal_places=3, read_only=True
    )
    total_units = serializers.IntegerField(read_only=True)

    class Meta:
        model = PackTemplate
        fields = [
            "id",
            "code",
            "name",
            "merchant",
            "merchant_name",
            "remark",
            "box_length_in",
            "box_width_in",
            "box_height_in",
            "box_weight_kg",
            "packing_material_weight_kg",
            "cbm",
            "net_weight_kg",
            "gross_weight_kg",
            "total_units",
            "is_library",
            "order",
            "is_active",
            "items",
            "created_at",
        ]

    def validate_items(self, items):
        if not items:
            raise serializers.ValidationError(
                "A template needs at least one piece, or it packs nothing."
            )
        # Keyed by piece: a product's two parts are two different things to
        # pack, and may legitimately both appear.
        seen = {
            (item["product"].id, item.get("part").id if item.get("part") else None)
            for item in items
        }
        if len(seen) != len(items):
            raise serializers.ValidationError(
                "The same piece is listed twice — combine them into one row."
            )
        return items

    @transaction.atomic
    def create(self, validated_data):
        items = validated_data.pop("items", [])
        template = PackTemplate.objects.create(**validated_data)
        self._write_items(template, items)
        return template

    @transaction.atomic
    def update(self, instance, validated_data):
        items = validated_data.pop("items", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if items is not None:
            instance.items.all().delete()
            self._write_items(instance, items)

        return instance

    @staticmethod
    def _write_items(template, items):
        PackTemplateItem.objects.bulk_create(
            [
                PackTemplateItem(
                    template=template,
                    product=item["product"],
                    part=item.get("part"),
                    quantity=item["quantity"],
                )
                for item in items
            ]
        )


# ── Orders ───────────────────────────────────────────────────────────


class ShippingAddressSerializer(serializers.Serializer):
    country = serializers.CharField(max_length=2, default="US")
    line1 = serializers.CharField(max_length=180, allow_blank=True, required=False)
    line2 = serializers.CharField(max_length=180, allow_blank=True, required=False)
    city = serializers.CharField(max_length=80, allow_blank=True, required=False)
    state = serializers.CharField(max_length=80, allow_blank=True, required=False)
    postal_code = serializers.CharField(max_length=20, allow_blank=True, required=False)


class DisplayOrderLineSerializer(serializers.ModelSerializer):
    product_style_no = serializers.CharField(source="product.style_no", read_only=True)
    product_description = serializers.CharField(
        source="product.description", read_only=True
    )
    store_code = serializers.CharField(source="store.code", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)

    class Meta:
        model = DisplayOrderLine
        fields = [
            "id",
            "store",
            "store_code",
            "store_name",
            "product",
            "product_style_no",
            "product_description",
            "color",
            "quantity",
        ]


class DisplayOrderSerializer(serializers.ModelSerializer):
    shipping_address = serializers.SerializerMethodField()
    merchant_name = serializers.CharField(source="merchant.name", read_only=True)
    lines = DisplayOrderLineSerializer(many=True, required=False)
    carton_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = DisplayOrder
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

    def validate(self, attrs):
        merchant = attrs.get("merchant", getattr(self.instance, "merchant", None))
        lines = attrs.get("lines")
        if lines is None:
            return attrs

        seen = set()
        for line in lines:
            store, product = line["store"], line["product"]
            if merchant and store.merchant_id != merchant.id:
                raise serializers.ValidationError(
                    {"lines": f"Store {store.code} belongs to another merchant."}
                )
            key = (store.id, product.id)
            if key in seen:
                raise serializers.ValidationError(
                    {
                        "lines": f"Store {store.code} lists {product.style_no} "
                        "twice — give it one quantity."
                    }
                )
            seen.add(key)
        return attrs

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
        lines = validated_data.pop("lines", [])
        order = DisplayOrder.objects.create(**validated_data)
        self._write_lines(order, lines)
        return order

    @transaction.atomic
    def update(self, instance, validated_data):
        lines = validated_data.pop("lines", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if lines is not None:
            instance.lines.all().delete()
            self._write_lines(instance, lines)

        return instance

    @staticmethod
    def _write_lines(order, lines):
        for line in lines:
            line.pop("id", None)
            DisplayOrderLine.objects.create(order=order, **line)


# ── Cartons ──────────────────────────────────────────────────────────


class DisplayCartonContentSerializer(serializers.ModelSerializer):
    product_style_no = serializers.CharField(source="product.style_no", read_only=True)
    part_name = serializers.CharField(source="part.name", default="", read_only=True)

    class Meta:
        model = DisplayCartonContent
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


class DisplayCartonSerializer(serializers.ModelSerializer):
    contents = DisplayCartonContentSerializer(many=True)
    cbm = serializers.DecimalField(max_digits=12, decimal_places=4, read_only=True)
    net_weight_kg = serializers.DecimalField(
        max_digits=12, decimal_places=3, read_only=True
    )
    template_code = serializers.CharField(
        source="step.template.code", default=None, read_only=True
    )
    store_code = serializers.CharField(source="store.code", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)

    class Meta:
        model = DisplayCarton
        fields = [
            "id",
            "carton_no",
            "step",
            "store",
            "store_code",
            "store_name",
            "template_code",
            "length_in",
            "width_in",
            "height_in",
            "box_weight_kg",
            "packing_material_weight_kg",
            "net_weight_kg",
            "gross_weight_kg",
            "cbm",
            "sort_order",
            "contents",
        ]


# ── The packing plan ─────────────────────────────────────────────────


class QuantityRowSerializer(serializers.Serializer):
    store = serializers.IntegerField()
    store_code = serializers.CharField(allow_blank=True)
    store_name = serializers.CharField(allow_blank=True)
    product = serializers.IntegerField()
    part = serializers.IntegerField(allow_null=True)
    style_no = serializers.CharField()
    part_name = serializers.CharField(allow_blank=True)
    description = serializers.CharField()
    quantity = serializers.IntegerField()


class StepRowSerializer(serializers.Serializer):
    sequence = serializers.IntegerField()
    store = serializers.IntegerField()
    store_code = serializers.CharField()
    store_name = serializers.CharField()
    template = serializers.IntegerField()
    template_code = serializers.CharField()
    template_name = serializers.CharField()
    count = serializers.IntegerField()
    carton_count = serializers.IntegerField()
    consumed = QuantityRowSerializer(many=True)
    remaining_after = QuantityRowSerializer(many=True)


class StoreRefSerializer(serializers.Serializer):
    store = serializers.IntegerField()
    store_code = serializers.CharField()
    store_name = serializers.CharField()


class StoreProgressSerializer(serializers.Serializer):
    store = serializers.IntegerField()
    store_code = serializers.CharField()
    store_name = serializers.CharField()
    ordered = serializers.IntegerField()
    packed = serializers.IntegerField()
    remaining = serializers.IntegerField()
    carton_count = serializers.IntegerField()
    is_done = serializers.BooleanField()


class ApplicableTemplateSerializer(serializers.Serializer):
    template = serializers.IntegerField()
    code = serializers.CharField()
    name = serializers.CharField()
    capacity = serializers.IntegerField()
    units_per_carton = serializers.IntegerField()


class ReconciliationSerializer(serializers.Serializer):
    store = serializers.IntegerField()
    store_code = serializers.CharField()
    product = serializers.IntegerField()
    style_no = serializers.CharField()
    ordered = serializers.IntegerField()
    packed = serializers.IntegerField()
    is_matched = serializers.BooleanField()


class SignalSerializer(serializers.Serializer):
    code = serializers.CharField()
    message = serializers.CharField()
    carton_id = serializers.IntegerField(allow_null=True)


class PackingPlanSerializer(serializers.Serializer):
    order = serializers.IntegerField()
    store = serializers.IntegerField(allow_null=True)
    stores = StoreProgressSerializer(many=True)
    steps = StepRowSerializer(many=True)
    remaining = QuantityRowSerializer(many=True)
    applicable_templates = ApplicableTemplateSerializer(many=True)
    reconciliation = ReconciliationSerializer(many=True)
    replicable = StoreRefSerializer(many=True)
    blockers = SignalSerializer(many=True)
    warnings = SignalSerializer(many=True)
    carton_count = serializers.IntegerField()
    total_quantity = serializers.IntegerField()
    total_gross_weight_kg = serializers.DecimalField(max_digits=14, decimal_places=3)
    total_cbm = serializers.DecimalField(max_digits=14, decimal_places=4)
    can_save = serializers.BooleanField()


class ApplyStepSerializer(serializers.Serializer):
    template = serializers.PrimaryKeyRelatedField(queryset=PackTemplate.objects.all())
    store = serializers.PrimaryKeyRelatedField(queryset=Store.objects.all())
    # Omit to apply the template as many times as it fits — the common case.
    count = serializers.IntegerField(required=False, allow_null=True, min_value=1)


class RecountStepSerializer(serializers.Serializer):
    count = serializers.IntegerField(min_value=1)


class ReplicatePlanSerializer(serializers.Serializer):
    """The store whose plan is being copied onto its identical neighbours."""

    store = serializers.PrimaryKeyRelatedField(queryset=Store.objects.all())


class AdjustmentSerializer(serializers.Serializer):
    sequence = serializers.IntegerField()
    template_code = serializers.CharField()
    was = serializers.IntegerField()
    now = serializers.IntegerField()
