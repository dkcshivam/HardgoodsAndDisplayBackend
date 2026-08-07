from django.db import transaction
from rest_framework import serializers

from .models import Product, ProductImage, ProductPart


class ProductImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductImage
        fields = ["id", "image", "is_main", "sort_order"]


class DerivedFieldsMixin(metaclass=serializers.SerializerMetaclass):
    """
    The three calculated values. Read-only everywhere: they come from the
    entered weights and dimensions, never from the request body.
    """

    net_weight_kg = serializers.DecimalField(
        max_digits=12, decimal_places=3, read_only=True
    )
    gross_weight_kg = serializers.DecimalField(
        max_digits=12, decimal_places=3, read_only=True
    )
    cbm = serializers.DecimalField(max_digits=12, decimal_places=4, read_only=True)


PACK_SPEC_FIELDS = [
    "box_type",
    "box_length_in",
    "box_width_in",
    "box_height_in",
    "product_weight_kg",
    "box_weight_kg",
    "packing_material_weight_kg",
    "net_weight_kg",
    "gross_weight_kg",
    "cbm",
]


class ProductPartSerializer(DerivedFieldsMixin, serializers.ModelSerializer):
    images = ProductImageSerializer(many=True, read_only=True)

    class Meta:
        model = ProductPart
        fields = [
            "id",
            "name",
            "description",
            "customs_description",
            "hsn_code",
            "length_in",
            "width_in",
            "height_in",
            "sort_order",
            "images",
            *PACK_SPEC_FIELDS,
        ]


class ProductListSerializer(serializers.ModelSerializer):
    """The lighter shape used by the products table — no parts, no images."""

    category_name = serializers.CharField(source="category.name", default="", read_only=True)
    product_group_name = serializers.CharField(
        source="product_group.name", default=None, read_only=True
    )
    part_count = serializers.IntegerField(source="parts.count", read_only=True)

    class Meta:
        model = Product
        fields = [
            "id",
            "style_no",
            "description",
            "category",
            "category_name",
            "product_group",
            "product_group_name",
            "is_multi_part",
            "part_count",
            "pack_per_box",
            "is_fragile",
            "status",
        ]


class ProductSerializer(DerivedFieldsMixin, serializers.ModelSerializer):
    """
    The full record, with parts written in the same request as the product.

    The product form is one screen, so it saves in one call — the frontend
    posts the product and its parts together and gets the whole thing back.
    """

    parts = ProductPartSerializer(many=True, required=False)
    images = ProductImageSerializer(many=True, read_only=True)

    category_name = serializers.CharField(source="category.name", default="", read_only=True)
    product_group_name = serializers.CharField(
        source="product_group.name", default=None, read_only=True
    )

    total_shipping_weight_kg = serializers.DecimalField(
        max_digits=12, decimal_places=3, read_only=True
    )
    total_shipping_cbm = serializers.DecimalField(
        max_digits=12, decimal_places=4, read_only=True
    )

    class Meta:
        model = Product
        fields = [
            "id",
            "style_no",
            "description",
            "category",
            "category_name",
            "product_group",
            "product_group_name",
            "customs_description",
            "hsn_code",
            "is_multi_part",
            "is_fragile",
            "status",
            "assembled_length_in",
            "assembled_width_in",
            "assembled_height_in",
            "assembled_weight_kg",
            "pack_per_box",
            "parts",
            "images",
            "total_shipping_weight_kg",
            "total_shipping_cbm",
            "created_at",
            "updated_at",
            *PACK_SPEC_FIELDS,
        ]

    def validate(self, attrs):
        is_multi_part = attrs.get(
            "is_multi_part",
            getattr(self.instance, "is_multi_part", False),
        )
        parts = attrs.get("parts")

        if is_multi_part:
            if attrs.get("box_type"):
                raise serializers.ValidationError(
                    {
                        "box_type": "A multi-part product has no box of its own — "
                        "each part carries its own."
                    }
                )
            if parts is not None and len(parts) < 2:
                raise serializers.ValidationError(
                    {"parts": "A multi-part product needs at least two parts."}
                )
        elif parts:
            raise serializers.ValidationError(
                {
                    "parts": "A single-box product has no parts. "
                    "Turn on is_multi_part first."
                }
            )

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        parts_data = validated_data.pop("parts", [])
        product = Product.objects.create(**validated_data)
        self._write_parts(product, parts_data)
        return product

    @transaction.atomic
    def update(self, instance, validated_data):
        parts_data = validated_data.pop("parts", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if parts_data is not None:
            # The form always sends the complete list of parts, so replacing
            # them wholesale matches what the user sees on screen.
            instance.parts.all().delete()
            self._write_parts(instance, parts_data)

        return instance

    @staticmethod
    def _write_parts(product, parts_data):
        for index, part in enumerate(parts_data):
            part.pop("id", None)
            part.setdefault("sort_order", index)
            ProductPart.objects.create(product=product, **part)
