from django.contrib import admin

from .models import (
    DisplayCarton,
    DisplayCartonContent,
    DisplayOrder,
    DisplayOrderLine,
    DisplayProduct,
    DisplayProductPart,
    PackStep,
    PackTemplate,
    PackTemplateItem,
)


class DisplayProductPartInline(admin.TabularInline):
    model = DisplayProductPart
    extra = 0
    fields = (
        "sort_order",
        "name",
        "customs_description",
        "hsn_code",
        "hts_code",
        "product_weight_kg",
        ("length_in", "width_in", "height_in"),
    )


@admin.register(DisplayProduct)
class DisplayProductAdmin(admin.ModelAdmin):
    list_display = (
        "style_no",
        "style_name",
        "description",
        "category",
        "packing",
        "product_weight_kg",
        "status",
    )
    list_filter = ("status", "is_multi_part", "is_delegate", "category")
    search_fields = ("style_no", "style_name", "description")
    readonly_fields = ("created_at", "updated_at")
    inlines = [DisplayProductPartInline]

    fieldsets = (
        (
            "Item",
            {
                "fields": (
                    "style_no",
                    "style_name",
                    "description",
                    "category",
                    "is_multi_part",
                    "status",
                )
            },
        ),
        ("Customs", {"fields": ("customs_description", "hsn_code", "hts_code")}),
        (
            "Size and weight",
            {
                "fields": (
                    ("length_in", "width_in", "height_in"),
                    "product_weight_kg",
                ),
                "description": (
                    "The item itself. Its box belongs to the pack template. "
                    "Leave empty on a multi-part product — its parts carry these."
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
        if not obj.is_multi_part:
            return "single piece"
        return f"{obj.parts.count()} parts"


class PackTemplateItemInline(admin.TabularInline):
    model = PackTemplateItem
    extra = 1
    fields = ("product", "part", "quantity")
    autocomplete_fields = ("product",)


@admin.register(PackTemplate)
class PackTemplateAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "name",
        "merchant",
        "total_units",
        "gross_weight_kg",
        "cbm",
        "is_library",
        "is_active",
    )
    list_filter = ("is_library", "is_active", "merchant")
    search_fields = ("code", "name")
    readonly_fields = ("created_at", "updated_at")
    inlines = [PackTemplateItemInline]

    fieldsets = (
        ("Template", {"fields": ("code", "name", "merchant", "remark")}),
        (
            "The box",
            {
                "fields": (
                    ("box_length_in", "box_width_in", "box_height_in"),
                    "box_weight_kg",
                    "packing_material_weight_kg",
                )
            },
        ),
        ("Availability", {"fields": ("is_library", "is_active")}),
        ("Record", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


class DisplayOrderLineInline(admin.TabularInline):
    model = DisplayOrderLine
    extra = 0
    fields = ("store", "store_position", "product", "color", "quantity")
    autocomplete_fields = ("store", "product")


class PackStepInline(admin.TabularInline):
    model = PackStep
    extra = 0
    fields = ("sequence", "store", "template", "count")
    readonly_fields = ("sequence",)
    autocomplete_fields = ("store",)


@admin.register(DisplayOrder)
class DisplayOrderAdmin(admin.ModelAdmin):
    list_display = ("number", "name", "merchant", "status", "carton_count", "created_at")
    list_filter = ("status", "merchant")
    search_fields = ("number", "name", "buyer_name")
    readonly_fields = ("number", "created_at", "updated_at")
    inlines = [DisplayOrderLineInline, PackStepInline]

    fieldsets = (
        ("Order", {"fields": ("number", "name", "merchant", "buyer_name", "status")}),
        (
            "Ship to",
            {
                "fields": (
                    "ship_country",
                    "ship_line1",
                    "ship_line2",
                    ("ship_city", "ship_state", "ship_postal_code"),
                )
            },
        ),
        ("Record", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )


class DisplayCartonContentInline(admin.TabularInline):
    model = DisplayCartonContent
    extra = 0
    fields = ("product", "part", "description", "quantity", "unit", "net_weight_kg")
    autocomplete_fields = ("product",)


@admin.register(DisplayCarton)
class DisplayCartonAdmin(admin.ModelAdmin):
    list_display = (
        "carton_no",
        "order",
        "store",
        "template_code",
        "size",
        "net_weight_kg",
        "gross_weight_kg",
        "cbm",
    )
    list_filter = ("order", "store")
    search_fields = ("carton_no", "order__number")
    inlines = [DisplayCartonContentInline]

    @admin.display(description="template")
    def template_code(self, obj):
        return obj.step.template.code if obj.step_id else "—"

    @admin.display(description="size (L × W × H in)")
    def size(self, obj):
        if obj.length_in is None:
            return "—"
        return f"{obj.length_in} × {obj.width_in} × {obj.height_in}"
