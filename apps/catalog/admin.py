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
        ("customs_description", "hsn_code"),
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
        "description",
        "category",
        "packing",
        "status",
    )
    list_filter = ("status", "is_multi_part", "is_fragile", "category")
    search_fields = ("style_no", "description", "customs_description", "hsn_code")
    inlines = [ProductImageInline, ProductPartInline]
    readonly_fields = ("derived", "created_at", "updated_at")

    fieldsets = (
        (
            "Identity",
            {
                "fields": (
                    "style_no",
                    "description",
                    "category",
                    ("is_fragile", "status"),
                )
            },
        ),
        (
            "Customs",
            {
                "description": "For a multi-part product these live on each part instead.",
                "fields": ("customs_description", "hsn_code"),
            },
        ),
        (
            "How it packs",
            {"fields": ("is_multi_part", "pack_per_box")},
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
    search_fields = ("name", "product__style_no", "hsn_code")
    inlines = [ProductImageInline]
