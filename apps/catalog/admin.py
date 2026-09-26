from django.contrib import admin

from .models import Product, ProductImage, ProductPart


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0
    fields = ("image", "is_main", "sort_order")


class ProductPartInline(admin.StackedInline):
    """Parts edit inside the product — one screen for the whole recipe."""

    model = ProductPart
    extra = 0
    fields = (
        ("name", "sort_order"),
        "description",
        ("customs_description", "hsn_code", "hts_code"),
        ("length_in", "width_in", "height_in"),
        "product_weight_kg",
        ("box_length_in", "box_width_in", "box_height_in"),
        "box_weight_kg",
        "packing_material_weight_kg",
        "derived",
    )
    readonly_fields = ("derived",)

    @admin.display(description="calculated")
    def derived(self, obj):
        if not obj or not obj.pk:
            return "— saves first —"
        return (
            f"net {obj.net_weight_kg} kg  ·  "
            f"gross {obj.gross_weight_kg} kg  ·  "
            f"{obj.cbm} CBM"
        )


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "style_no",
        "style_name",
        "description",
        "category",
        "packing",
        "status",
    )
    list_filter = ("status", "is_multi_part", "is_delegate", "category")
    # A multi-part product keeps its customs codes on the parts, so a code
    # search has to look there too to find it.
    search_fields = (
        "style_no",
        "style_name",
        "description",
        "customs_description",
        "hsn_code",
        "hts_code",
        "parts__name",
        "parts__hsn_code",
        "parts__hts_code",
    )
    search_help_text = (
        "Search by style no, name, description, or an HSN/HTS code — "
        "the product's own or any of its parts'."
    )
    inlines = [ProductImageInline, ProductPartInline]
    readonly_fields = ("derived", "created_at", "updated_at")

    fieldsets = (
        (
            "Identity",
            {
                "fields": (
                    "style_no",
                    "style_name",
                    "description",
                    "category",
                    "status",
                )
            },
        ),
        (
            "Customs",
            {
                "description": "For a multi-part product these live on each part instead.",
                "fields": ("customs_description", "hsn_code", "hts_code"),
            },
        ),
        (
            "How it packs",
            {"fields": ("is_multi_part", "is_delegate", "pack_per_box")},
        ),
        (
            "Single-box: the carton",
            {
                "description": "Leave empty for multi-part products — parts carry their own.",
                "fields": (
                    ("box_length_in", "box_width_in", "box_height_in"),
                    "product_weight_kg",
                    "box_weight_kg",
                    "packing_material_weight_kg",
                    "derived",
                ),
            },
        ),
        (
            "Multi-part: assembled reference",
            {
                "description": (
                    "Size and weight of the finished item. Reference only — "
                    "it never ships assembled, so this takes no part in any calculation."
                ),
                "fields": (
                    (
                        "assembled_length_in",
                        "assembled_width_in",
                        "assembled_height_in",
                    ),
                    "assembled_weight_kg",
                ),
            },
        ),
        ("Record", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        # Same rule as the API: the shape is fixed once the product exists.
        return (*fields, "is_multi_part") if obj else fields

    @admin.display(description="packing")
    def packing(self, obj):
        if obj.is_multi_part:
            return f"{obj.parts.count()} parts"
        return f"{obj.pack_per_box} per box"

    @admin.display(description="calculated")
    def derived(self, obj):
        if not obj or not obj.pk:
            return "— save first —"
        return (
            f"net {obj.net_weight_kg} kg  ·  "
            f"gross {obj.gross_weight_kg} kg  ·  "
            f"{obj.cbm} CBM"
        )


@admin.register(ProductPart)
class ProductPartAdmin(admin.ModelAdmin):
    list_display = ("product", "name", "net_weight_kg", "gross_weight_kg", "cbm")
    search_fields = (
        "name",
        "product__style_no",
        "product__style_name",
        "customs_description",
        "hsn_code",
        "hts_code",
    )
    search_help_text = "Search by part name, its product's style, or an HSN/HTS code."
    inlines = [ProductImageInline]
