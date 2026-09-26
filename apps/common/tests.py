import tempfile

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.catalog.models import Product, ProductPart
from apps.masters.models import Merchant
from apps.orders.models import Order, OrderLine

from .testing import local_storage


@override_settings(STORAGES=local_storage(tempfile.mkdtemp()))
class AdminSearchTests(TestCase):
    def setUp(self):
        self.client.force_login(
            get_user_model().objects.create_superuser("admin", "admin@example.com", "x")
        )

    def search(self, model, query):
        meta = model._meta
        url = reverse(f"admin:{meta.app_label}_{meta.model_name}_changelist")
        response = self.client.get(url, {"q": query})
        self.assertEqual(response.status_code, 200)
        return list(response.context["cl"].result_list)

    def test_every_admin_list_can_be_searched(self):
        # A search field naming a missing column passes every check at start-up
        # and fails only when someone first types into that box.
        for model, model_admin in admin.site._registry.items():
            if model_admin.search_fields:
                with self.subTest(model=model.__name__):
                    self.search(model, "x")

    def test_a_multi_part_product_is_found_by_its_parts_hsn_code(self):
        table = Product.objects.create(
            style_no="TBL-01", description="Table", is_multi_part=True
        )
        ProductPart.objects.create(product=table, name="Top", hsn_code="94036000")

        self.assertEqual(self.search(Product, "94036000"), [table])

    def test_an_order_is_found_once_by_a_style_on_several_lines(self):
        order = Order.objects.create(
            name="Spring", merchant=Merchant.objects.create(code="UO", name="Urban")
        )
        for style in ("CHR-01", "CHR-02"):
            OrderLine.objects.create(
                order=order,
                product=Product.objects.create(style_no=style, description="Chair"),
                quantity=1,
            )

        self.assertEqual(self.search(Order, "CHR"), [order])
