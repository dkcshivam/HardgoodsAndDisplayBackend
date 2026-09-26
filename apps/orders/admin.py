from django.contrib import admin

from .models import Carton, CartonContent, Order, OrderLine


class OrderLineInline(admin.TabularInline):
    model = OrderLine
    extra = 0
    fields = ("product", "color", "quantity")
    autocomplete_fields = ("product",)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("number", "name", "merchant", "status", "carton_count", "created_at")
    list_filter = ("status", "merchant")
    search_fields = (
        "number",
        "name",
        "buyer_name",
        "merchant__code",
        "merchant__name",
        "lines__product__style_no",
    )
    search_help_text = (
        "Search by order number, name, buyer, merchant, or a style on the order."
    )
    readonly_fields = ("number", "created_at", "updated_at")
    inlines = [OrderLineInline]

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


class CartonContentInline(admin.TabularInline):
    model = CartonContent
    extra = 0
    autocomplete_fields = ("product", "part")


@admin.register(Carton)
class CartonAdmin(admin.ModelAdmin):
    list_display = (
        "carton_no",
        "order",
        "size",
        "net_weight_kg",
        "gross_weight_kg",
        "cbm",
    )
    list_filter = ("order",)
    search_fields = ("carton_no", "order__number", "contents__product__style_no")
    search_help_text = "Search by carton no, order number, or a style packed in it."
    inlines = [CartonContentInline]

    @admin.display(description="size (L × W × H in)")
    def size(self, obj):
        if obj.length_in is None:
            return "—"
        return f"{obj.length_in} × {obj.width_in} × {obj.height_in}"
