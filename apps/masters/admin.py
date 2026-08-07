from django.contrib import admin

from .models import BoxType, Category, Merchant, ProductGroup


@admin.register(BoxType)
class BoxTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "size", "max_weight_kg", "cbm", "is_active")
    list_filter = ("is_active",)
    search_fields = ("code", "name")

    @admin.display(description="size (L × W × H in)")
    def size(self, obj):
        return f"{obj.length_in} × {obj.width_in} × {obj.height_in}"


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(ProductGroup)
class ProductGroupAdmin(admin.ModelAdmin):
    list_display = ("name", "remark")
    search_fields = ("name",)


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "contact_name", "city", "country", "is_active")
    list_filter = ("is_active", "country")
    search_fields = ("code", "name", "contact_name", "email")
