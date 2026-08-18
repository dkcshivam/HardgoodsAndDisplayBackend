from django.db import transaction
from rest_framework import serializers

from .models import Product, ProductImage, ProductPart


class ProductImageSerializer(serializers.ModelSerializer):
    """Read nested under a product or part; written by the upload endpoint."""

    class Meta:
        model = ProductImage
        fields = ["id", "product", "part", "image", "is_main", "sort_order"]

    def validate(self, attrs):
        product = attrs.get("product", getattr(self.instance, "product", None))
        part = attrs.get("part", getattr(self.instance, "part", None))
        if bool(product) == bool(part):
            raise serializers.ValidationError(
                "A photo belongs to exactly one owner — send either product or part."
            )
        return attrs


class DerivedFieldsMixin(metaclass=serializers.SerializerMetaclass):
    """Derived from the entered weights, never taken from the request body."""

    net_weight_kg = serializers.DecimalField(
        max_digits=12, decimal_places=3, read_only=True
    )
    gross_weight_kg = serializers.DecimalField(
        max_digits=12, decimal_places=3, read_only=True
    )
    cbm = serializers.DecimalField(max_digits=12, decimal_places=4, read_only=True)


PACK_SPEC_FIELDS = [
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


def _unanswered(instance, attrs, field) -> bool:
    """
    Blank on the way in and blank on the row already. Falling back to the
    instance keeps a PATCH of one field from failing on the other seven.
    """
    value = attrs.get(field, getattr(instance, field, None))
    return value is None or value == ""


#: A carton cannot be built, weighed or cleared through customs without
#: these, so nothing that owns a box is allowed to leave them empty.
BOXED_PIECE_REQUIRED = [
    "customs_description",
    "hsn_code",
    "box_length_in",
    "box_width_in",
    "box_height_in",
    "product_weight_kg",
    "packing_material_weight_kg",
    "box_weight_kg",
]


class ProductPartSerializer(DerivedFieldsMixin, serializers.ModelSerializer):
    # Kept on write so an edit can match a payload row to the part it edits;
    # without it every save would recreate the parts and drop their photos.
    id = serializers.IntegerField(required=False)
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
        # A part owns the box its half of the product ships in, so it answers
        # for all of it — the product above has none of these to fall back on.
        extra_kwargs = {
            "name": {"required": True, "allow_blank": False},
            "customs_description": {"required": True, "allow_blank": False},
            "hsn_code": {"required": True, "allow_blank": False},
            **{
                field: {"required": True, "allow_null": False}
                for field in BOXED_PIECE_REQUIRED
                if not field.endswith(("description", "code"))
            },
        }


class ProductListSerializer(serializers.ModelSerializer):
    """The lighter shape used by the products table — no parts, no images."""

    category_name = serializers.CharField(source="category.name", default="", read_only=True)
    part_count = serializers.IntegerField(source="parts.count", read_only=True)
    main_image = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "style_no",
            "description",
            "category",
            "category_name",
            "is_multi_part",
            "part_count",
            "pack_per_box",
            "main_image",
            "status",
        ]

    def get_main_image(self, product):
        # Images order main-first, so the first one is the one to show.
        image = next(iter(product.images.all()), None)
        if not image:
            return None
        request = self.context.get("request")
        url = image.image.url
        return request.build_absolute_uri(url) if request else url


class ProductSerializer(DerivedFieldsMixin, serializers.ModelSerializer):
    """The product form is one screen, so it saves in one call — parts included."""

    parts = ProductPartSerializer(many=True, required=False)
    images = ProductImageSerializer(many=True, read_only=True)

    category_name = serializers.CharField(source="category.name", default="", read_only=True)

    total_shipping_weight_kg = serializers.DecimalField(
        max_digits=12, decimal_places=3, read_only=True
    )
    total_shipping_cbm = serializers.DecimalField(
        max_digits=12, decimal_places=4, read_only=True
    )
    # The database already refuses the delete (PROTECT). This lets the form
    # say so before somebody clicks it and reads an error instead.
    is_in_use = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "style_no",
            "description",
            "category",
            "category_name",
            "customs_description",
            "hsn_code",
            "is_multi_part",
            "is_in_use",
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

    def get_is_in_use(self, product) -> bool:
        """On an order, so it can no longer be deleted."""
        return product.order_lines.exists()

    def validate(self, attrs):
        is_multi_part = attrs.get(
            "is_multi_part",
            getattr(self.instance, "is_multi_part", False),
        )
        parts = attrs.get("parts")

        # The shape decides how every carton for this SKU is built, so orders
        # already packed under one shape would silently change meaning.
        if self.instance and is_multi_part != self.instance.is_multi_part:
            raise serializers.ValidationError(
                {
                    "is_multi_part": "How a product packs is fixed once it is saved. "
                    "Create a new style number for a different shape."
                }
            )

        if is_multi_part:
            own_box = [f for f in Product.OWN_BOX_FIELDS if attrs.get(f) is not None]
            if own_box:
                raise serializers.ValidationError(
                    {
                        own_box[0]: "A multi-part product has no box of its own — "
                        "each part carries its own box and weights."
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
        else:
            # It owns the box itself, so it answers for the box itself. A
            # multi-part product is exempt: its parts were checked above.
            missing = {
                field: "Required."
                for field in BOXED_PIECE_REQUIRED
                if _unanswered(self.instance, attrs, field)
            }
            pack_per_box = attrs.get(
                "pack_per_box", getattr(self.instance, "pack_per_box", 1)
            )
            if not pack_per_box or pack_per_box < 1:
                missing["pack_per_box"] = "At least 1."
            if missing:
                raise serializers.ValidationError(missing)

        return attrs

    @transaction.atomic
    def create(self, validated_data):
        parts_data = validated_data.pop("parts", [])
        product = Product.objects.create(**validated_data)
        self._sync_parts(product, parts_data)
        return product

    @transaction.atomic
    def update(self, instance, validated_data):
        parts_data = validated_data.pop("parts", None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if parts_data is not None:
            # The form always sends the complete list.
            self._sync_parts(instance, parts_data)

        return instance

    @staticmethod
    def _sync_parts(product, parts_data):
        """
        Match payload rows to existing parts by id and update them in place.
        Recreating them instead would cascade their photos away on every save,
        and orphan any carton content pointing at them.
        """
        existing = {part.id: part for part in product.parts.all()}
        kept = set()

        for index, data in enumerate(parts_data):
            part_id = data.pop("id", None)
            data.setdefault("sort_order", index)
            part = existing.get(part_id)

            if part is None:
                part = ProductPart.objects.create(product=product, **data)
            else:
                for attr, value in data.items():
                    setattr(part, attr, value)
                part.save()

            kept.add(part.id)

        product.parts.exclude(id__in=kept).delete()
