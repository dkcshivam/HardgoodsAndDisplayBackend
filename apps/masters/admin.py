from django.contrib import admin

from .models import Category, Merchant, Store


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)
    search_help_text = "Search by name."


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "contact_name", "city", "country", "is_active")
    list_filter = ("is_active", "country")
    search_fields = ("code", "name", "contact_name", "email", "phone", "city")
    search_help_text = "Search by code, name, contact, email, phone or city."


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ("name", "ship_city", "ship_state", "is_active")
    list_filter = ("is_active", "ship_country")
    search_fields = (
        "name",
        "contact_name",
        "email",
        "phone",
        "ship_city",
        "ship_state",
        "ship_postal_code",
    )
    search_help_text = "Search by name, contact, email, phone, city, state or ZIP."
