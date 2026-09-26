from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve
from rest_framework.routers import DefaultRouter

from apps.catalog.views import ProductImageViewSet, ProductViewSet
from apps.display.views import (
    DisplayOrderViewSet,
    DisplayProductImageViewSet,
    DisplayProductViewSet,
    PackTemplateViewSet,
)
from apps.masters.views import CategoryViewSet, MerchantViewSet, StoreViewSet
from apps.orders.views import OrderViewSet

router = DefaultRouter()

router.register("categories", CategoryViewSet)
router.register("merchants", MerchantViewSet)
router.register("stores", StoreViewSet)
router.register("products", ProductViewSet)
router.register("product-images", ProductImageViewSet)
router.register("orders", OrderViewSet)

router.register("display-products", DisplayProductViewSet)
router.register("display-product-images", DisplayProductImageViewSet)
router.register("pack-templates", PackTemplateViewSet)
router.register("display-orders", DisplayOrderViewSet)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(router.urls)),
    path("api/auth/", include("rest_framework.urls")),  # browsable API login
]

# In production the admin's CSS is served by Django itself: for a handful of
# users that is simpler than a separate file server. Images come straight from
# S3. With DEBUG on, runserver already serves static files.
if not settings.DEBUG:
    urlpatterns += [
        re_path(r"^static/(?P<path>.*)$", serve, {"document_root": settings.STATIC_ROOT}),
    ]

admin.site.site_header = "DKC Packing"
admin.site.site_title = "DKC Packing"
admin.site.index_title = "Operations"
