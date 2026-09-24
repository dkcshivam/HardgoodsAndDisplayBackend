from django.db import transaction
from rest_framework import serializers

from apps.masters.models import Store

from . import services
from .models import (
    DisplayCarton,
    DisplayCartonContent,
    DisplayOrder,
    DisplayOrderLine,
    DisplayOrderRate,
    DisplayProduct,
    DisplayProductImage,
    DisplayProductPart,
    PackTemplate,
    PackTemplateItem,
)


class DisplayProductImageSerializer(serializers.ModelSerializer):
    """Read nested under a product or part; written by the upload endpoint."""

    class Meta:
        model = DisplayProductImage
        fields = ["id", "product", "part", "image", "is_main", "sort_order"]

    def validate(self, attrs):
        product = attrs.get("product", getattr(self.instance, "product", None))
        part = attrs.get("part", getattr(self.instance, "part", None))
        if bool(product) == bool(part):
            raise serializers.ValidationError(
                "A photo belongs to exactly one owner — send either product or part."
            )
        return attrs


def _unanswered(instance, attrs, field) -> bool:
    """
    Blank on the way in and blank on the row already. Falling back to the
    instance keeps a PATCH of one field from failing on the others.
    """
    value = attrs.get(field, getattr(instance, field, None))
    return value is None or value == ""


#: A display product owns no box, so what it must answer for is itself: the
#: size and weight a template checks a carton's fit against. The customs
#: fields (description, HSN, HTS) are optional — filled when they are known.
PIECE_REQUIRED = [
    "product_weight_kg",
    "length_in",
    "width_in",
    "height_in",
]


class DisplayProductPartSerializer(serializers.ModelSerializer):
    # Kept on write so an edit can match a payload row to the part it edits;
    # without it every save would recreate the parts and orphan the template
    # items and carton contents pointing at them.
    id = serializers.IntegerField(required=False)
    unit_cbm = serializers.DecimalField(max_digits=12, decimal_places=4, read_only=True)
    images = DisplayProductImageSerializer(many=True, read_only=True)

    class Meta:
        model = DisplayProductPart
        fields = [
            "id",
            "images",
            "name",
            "is_delegate",
            "description",
            "customs_description",
            "hsn_code",
            "hts_code",
            "product_weight_kg",
            "length_in",
            "width_in",
            "height_in",
            "unit_cbm",
            "sort_order",
        ]
        # A part is packed on its own, so it answers on its own — the product
        # above holds none of these for a multi-part SKU.
        extra_kwargs = {
            "name": {"required": True, "allow_blank": False},
            **{
                field: {"required": True, "allow_null": False}
                for field in PIECE_REQUIRED
                if field.endswith(("_kg", "_in"))
            },
        }


class DisplayProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)
    unit_cbm = serializers.DecimalField(max_digits=12, decimal_places=4, read_only=True)
    parts = DisplayProductPartSerializer(many=True, required=False)
    images = DisplayProductImageSerializer(many=True, read_only=True)

    class Meta:
        model = DisplayProduct
        fields = [
            "id",
            "style_no",
            "style_name",
            "is_delegate",
            "description",
            "category",
            "category_name",
            "customs_description",
            "hsn_code",
            "hts_code",
            "is_multi_part",
            "status",
            "product_weight_kg",
            "length_in",
            "width_in",
            "height_in",
            "unit_cbm",
            "parts",
            "images",
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
        else:
            # Handled whole, so it answers whole. A multi-part product is
            # exempt: its parts were checked by their own serializer.
            missing = {
                field: "Required."
                for field in PIECE_REQUIRED
                if _unanswered(self.instance, attrs, field)
            }
            if missing:
                raise serializers.ValidationError(missing)

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
    product_style_name = serializers.CharField(
        source="product.style_name", read_only=True
    )
    product_description = serializers.CharField(
        source="product.description", read_only=True
    )
    store_name = serializers.CharField(source="store.name", read_only=True)

    class Meta:
        model = DisplayOrderLine
        fields = [
            "id",
            "store",
            "store_name",
            "product",
            "product_style_no",
            "product_style_name",
            "product_description",
            "color",
            "quantity",
        ]


class DisplayOrderRateSerializer(serializers.ModelSerializer):
    product_style_no = serializers.CharField(source="product.style_no", read_only=True)

    class Meta:
        model = DisplayOrderRate
        fields = ["id", "product", "product_style_no", "rate_usd"]


class DisplayOrderSerializer(serializers.ModelSerializer):
    shipping_address = serializers.SerializerMethodField()
    merchant_name = serializers.CharField(source="merchant.name", read_only=True)
    lines = DisplayOrderLineSerializer(many=True, required=False)
    rates = DisplayOrderRateSerializer(many=True, required=False)
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
            "rates",
            "carton_count",
            "export_details",
            "created_at",
        ]
        read_only_fields = ["number", "status"]
        # The packing list prints it and a customs broker reads it, so an
        # order without a buyer is one somebody has to chase later.
        extra_kwargs = {"buyer_name": {"required": True, "allow_blank": False}}

    def validate(self, attrs):
        lines = attrs.get("lines")
        if lines is None:
            return attrs

        seen = set()
        for line in lines:
            store, product = line["store"], line["product"]
            key = (store.id, product.id)
            if key in seen:
                raise serializers.ValidationError(
                    {
                        "lines": f"Store {store.name} lists {product.style_no} "
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
        rates = validated_data.pop("rates", [])
        order = DisplayOrder.objects.create(**validated_data)
        self._write_lines(order, lines)
        self._sync_rates(order, rates)
        return order

    @transaction.atomic
    def update(self, instance, validated_data):
        lines = validated_data.pop("lines", None)
        rates = validated_data.pop("rates", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if lines is not None:
            # The form always sends the complete list.
            self._sync_lines(instance, lines)
        if rates is not None:
            self._sync_rates(instance, rates)

        return instance

    @staticmethod
    def _sync_rates(order, rates_data):
        """Rewritten wholesale — a rate carries no history of its own."""
        order.rates.exclude(
            product__in=[row["product"] for row in rates_data]
        ).delete()
        for row in rates_data:
            DisplayOrderRate.objects.update_or_create(
                order=order,
                product=row["product"],
                defaults={"rate_usd": row["rate_usd"]},
            )

    @staticmethod
    def _store_positions(lines) -> dict[int, int]:
        """
        The stores in the order the payload first names them. The form sends
        its lines store by store in the sheet's column order, so this is the
        sheet's order without the API needing a second list to keep in step.
        """
        positions: dict[int, int] = {}
        for line in lines:
            positions.setdefault(line["store"].id, len(positions) + 1)
        return positions

    @classmethod
    def _write_lines(cls, order, lines):
        positions = cls._store_positions(lines)
        for line in lines:
            line.pop("id", None)
            line["store_position"] = positions[line["store"].id]
            DisplayOrderLine.objects.create(order=order, **line)

    @classmethod
    def _sync_lines(cls, order, lines_data):
        """
        Match payload rows to the lines they edit by store and product — the
        pair is unique per order, and it is the key the cartons are counted
        under, so the packed check lines up exactly.

        Rewriting the lines wholesale would strand cartons instead: both
        reconciliation and the store overview are derived from the lines, so a
        packed line that disappears takes its boxes out of every check that
        would have caught them.
        """
        floors = services.packed_floor(order)
        existing = {
            (line.store_id, line.product_id): line
            for line in order.lines.select_related("store", "product")
        }
        kept = set()
        positions = cls._store_positions(lines_data)

        for data in lines_data:
            data.pop("id", None)
            data["store_position"] = positions[data["store"].id]
            key = (data["store"].id, data["product"].id)
            line = existing.get(key)

            if line is None:
                DisplayOrderLine.objects.create(order=order, **data)
            else:
                floor = floors.get(key, 0)
                if data["quantity"] < floor:
                    raise serializers.ValidationError(
                        {
                            "lines": (
                                f"Store {line.store.name} already has {floor} of "
                                f"{line.product.style_no} in cartons. Drop those "
                                "steps before ordering fewer."
                            )
                        }
                    )
                for attr, value in data.items():
                    setattr(line, attr, value)
                line.save()

            kept.add(key)

        for key, line in existing.items():
            if key in kept:
                continue
            if floor := floors.get(key, 0):
                raise serializers.ValidationError(
                    {
                        "lines": (
                            f"Store {line.store.name} already has {floor} of "
                            f"{line.product.style_no} in cartons. Drop those steps "
                            "before taking it off the order."
                        )
                    }
                )
            line.delete()


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
    store_name = serializers.CharField(source="store.name", read_only=True)

    class Meta:
        model = DisplayCarton
        fields = [
            "id",
            "carton_no",
            "step",
            "store",
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
    store_name = serializers.CharField(allow_blank=True)
    product = serializers.IntegerField()
    part = serializers.IntegerField(allow_null=True)
    style_no = serializers.CharField()
    style_name = serializers.CharField(allow_blank=True)
    part_name = serializers.CharField(allow_blank=True)
    description = serializers.CharField()
    quantity = serializers.IntegerField()


class StepRowSerializer(serializers.Serializer):
    sequence = serializers.IntegerField()
    store = serializers.IntegerField()
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
    store_name = serializers.CharField()


class StoreProgressSerializer(serializers.Serializer):
    store = serializers.IntegerField()
    store_name = serializers.CharField()
    ordered = serializers.IntegerField()
    packed = serializers.IntegerField()
    remaining = serializers.IntegerField()
    carton_count = serializers.IntegerField()
    is_done = serializers.BooleanField()


class TemplateContentSerializer(serializers.Serializer):
    style_no = serializers.CharField()
    part_name = serializers.CharField()
    quantity = serializers.IntegerField()


class ApplicableTemplateSerializer(serializers.Serializer):
    template = serializers.IntegerField()
    code = serializers.CharField()
    name = serializers.CharField()
    capacity = serializers.IntegerField()
    units_per_carton = serializers.IntegerField()
    contents = TemplateContentSerializer(many=True)


class ReconciliationSerializer(serializers.Serializer):
    store = serializers.IntegerField()
    store_name = serializers.CharField()
    product = serializers.IntegerField()
    style_no = serializers.CharField()
    ordered = serializers.IntegerField()
    packed = serializers.IntegerField()
    packed_floor = serializers.IntegerField()
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
