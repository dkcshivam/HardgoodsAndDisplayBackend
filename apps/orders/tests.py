from decimal import Decimal

from django.urls import reverse
from rest_framework.test import APITestCase

from apps.catalog.models import Product, ProductPart
from apps.masters.models import BoxType, Merchant

from .models import Order, OrderLine


class PackingApiTests(APITestCase):
    def setUp(self):
        self.box = BoxType.objects.create(
            code="STD-M", name="Standard Medium",
            length_in=40, width_in=30, height_in=24,
        )
        self.merchant = Merchant.objects.create(code="UO", name="Urban Outfitters")

        self.chair = Product.objects.create(
            style_no="CHR-01", description="Chair", pack_per_box=2,
            box_type=self.box,
            product_weight_kg=Decimal("6"),
            box_weight_kg=Decimal("0.5"),
            packing_material_weight_kg=Decimal("0.2"),
        )
        self.table = Product.objects.create(
            style_no="TBL-01", description="Table", is_multi_part=True,
        )
        for name in ("Top", "Legs"):
            ProductPart.objects.create(
                product=self.table, name=name, box_type=self.box,
                product_weight_kg=Decimal("10"),
                box_weight_kg=Decimal("1"),
                packing_material_weight_kg=Decimal("0.5"),
            )

        self.order = Order.objects.create(name="Test", merchant=self.merchant)
        OrderLine.objects.create(order=self.order, product=self.chair, quantity=6)
        OrderLine.objects.create(order=self.order, product=self.table, quantity=2)

    def url(self, name):
        return reverse(f"order-{name}", args=[self.order.pk])

    def payload(self, cartons):
        """Reshape a GET response the way the packing screen posts it back."""
        return {
            "cartons": [
                {
                    "carton_no": carton["carton_no"],
                    "box_type": carton["box_type"],
                    "length_in": carton["length_in"],
                    "width_in": carton["width_in"],
                    "height_in": carton["height_in"],
                    "gross_weight_kg": carton["gross_weight_kg"],
                    "sort_order": index,
                    "contents": [
                        {
                            "product": item["product"],
                            "part": item["part"],
                            "description": item["description"],
                            "quantity": item["quantity"],
                            "unit": item["unit"],
                            "net_weight_kg": item["net_weight_kg"],
                        }
                        for item in carton["contents"]
                    ],
                }
                for index, carton in enumerate(cartons)
            ]
        }

    def test_auto_pack_splits_by_parts_and_pack_per_box(self):
        response = self.client.post(self.url("auto-pack"))
        self.assertEqual(response.status_code, 200)
        # 6 chairs at 2/box = 3, plus 2 tables x 2 parts = 4.
        self.assertEqual(response.data["carton_count"], 7)
        self.assertTrue(response.data["can_save"])

    def test_packing_accepts_both_get_and_put(self):
        """Regression: a second @action on the same url_path shadowed the PUT."""
        self.client.post(self.url("auto-pack"))

        read = self.client.get(self.url("packing"))
        self.assertEqual(read.status_code, 200)

        saved = self.client.put(
            self.url("packing"), self.payload(read.data["cartons"]), format="json"
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.data["carton_count"], 7)

    def test_saving_a_draft_plan_advances_the_order(self):
        self.client.post(self.url("auto-pack"))
        read = self.client.get(self.url("packing"))
        self.client.put(self.url("packing"), self.payload(read.data["cartons"]), format="json")

        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "packing")

    def test_short_plan_is_rejected_and_rolled_back(self):
        self.client.post(self.url("auto-pack"))
        read = self.client.get(self.url("packing"))

        short = self.payload(read.data["cartons"][:-1])
        response = self.client.put(self.url("packing"), short, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertTrue(
            any(b["code"] == "quantity_mismatch" for b in response.data["blockers"])
        )
        self.assertEqual(self.order.cartons.count(), 7)

    def test_multi_part_reconciliation_takes_the_minimum(self):
        """Three tops and two leg sets is two tables, not two and a half."""
        self.client.post(self.url("auto-pack"))
        top = self.table.parts.first()
        self.order.cartons.filter(contents__part=top).first().delete()

        response = self.client.get(self.url("packing"))
        row = next(
            r for r in response.data["reconciliation"] if r["style_no"] == "TBL-01"
        )
        self.assertEqual(row["packed"], 1)
        self.assertFalse(row["is_matched"])

    def test_cannot_mark_packed_while_blocked(self):
        response = self.client.post(self.url("advance-status"))
        self.assertEqual(response.status_code, 200)  # draft -> packing

        response = self.client.post(self.url("advance-status"))
        self.assertEqual(response.status_code, 400)  # packing -> packed is gated
