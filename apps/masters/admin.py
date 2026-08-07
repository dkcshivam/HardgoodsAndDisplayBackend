from django.contrib import admin

from .models import Category, Merchant


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name",)


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "contact_name", "city", "country", "is_active")
    list_filter = ("is_active", "country")
    search_fields = ("code", "name", "contact_name", "email")
