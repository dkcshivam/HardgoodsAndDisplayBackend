from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.catalog.views import ProductImageViewSet, ProductViewSet
from apps.display.views import (
    DisplayOrderViewSet,
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
router.register("pack-templates", PackTemplateViewSet)
router.register("display-orders", DisplayOrderViewSet)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include(router.urls)),
    path("api/auth/", include("rest_framework.urls")),  # browsable API login
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

admin.site.site_header = "DKC Packing"
admin.site.site_title = "DKC Packing"
admin.site.index_title = "Operations"
