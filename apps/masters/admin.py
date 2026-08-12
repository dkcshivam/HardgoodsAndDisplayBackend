from django.contrib import admin

from .models import Category, Merchant, Store


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


class StoreInline(admin.TabularInline):
    model = Store
    extra = 0
    fields = ("code", "name", "ship_city", "ship_state", "is_active")
    show_change_link = True


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "contact_name", "city", "country", "is_active")
    list_filter = ("is_active", "country")
    search_fields = ("code", "name", "contact_name", "email")
    inlines = [StoreInline]


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "merchant", "ship_city", "ship_state", "is_active")
    list_filter = ("is_active", "merchant", "ship_country")
    search_fields = ("code", "name", "contact_name", "ship_city")
    list_select_related = ("merchant",)
