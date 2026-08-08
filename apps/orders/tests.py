from decimal import Decimal
from io import BytesIO

from django.urls import reverse
from openpyxl import load_workbook
from rest_framework.test import APITestCase

from apps.catalog.models import Product, ProductPart
from apps.masters.models import Merchant

from .models import Order, OrderLine


class OrderFixture(APITestCase):
    """One order: six chairs two-to-a-box, and two tables of two parts each."""

    def setUp(self):
        self.merchant = Merchant.objects.create(code="UO", name="Urban Outfitters")

        self.chair = Product.objects.create(
            style_no="CHR-01", description="Chair", pack_per_box=2,
            box_length_in=40, box_width_in=30, box_height_in=24,
            product_weight_kg=Decimal("6"),
            box_weight_kg=Decimal("0.5"),
            packing_material_weight_kg=Decimal("0.2"),
        )
        self.table = Product.objects.create(
            style_no="TBL-01", description="Table", is_multi_part=True,
        )
        for name in ("Top", "Legs"):
            ProductPart.objects.create(
                product=self.table, name=name,
                box_length_in=40, box_width_in=30, box_height_in=24,
                product_weight_kg=Decimal("10"),
                box_weight_kg=Decimal("1"),
                packing_material_weight_kg=Decimal("0.5"),
            )

        self.order = Order.objects.create(name="Test", merchant=self.merchant)
        OrderLine.objects.create(
            order=self.order, product=self.chair, quantity=6, color="Charcoal Wash"
        )
        OrderLine.objects.create(
            order=self.order, product=self.table, quantity=2, color="Natural Oak"
        )

    def url(self, name):
        return reverse(f"order-{name}", args=[self.order.pk])

    def payload(self, cartons):
        """Reshape a GET response the way the packing screen posts it back."""
        return {
            "cartons": [
                {
                    "carton_no": carton["carton_no"],
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


class PackingApiTests(OrderFixture):
    def test_auto_pack_splits_by_parts_and_pack_per_box(self):
        response = self.client.post(self.url("auto-pack"))
        self.assertEqual(response.status_code, 200)
        # 6 chairs at 2/box = 3, plus 2 tables x 2 parts = 4.
        self.assertEqual(response.data["carton_count"], 7)
        self.assertTrue(response.data["can_save"])

    def test_a_parts_cartons_are_numbered_together(self):
        """One unbroken run per part, so the packing list can name a range
        rather than every second number."""
        self.client.post(self.url("auto-pack"))
        cartons = self.client.get(self.url("packing")).data["cartons"]

        by_part = {}
        for carton in cartons:
            for content in carton["contents"]:
                by_part.setdefault(content["description"], []).append(
                    carton["carton_no"]
                )

        self.assertEqual(by_part["Table — Top"], ["CTN-004", "CTN-005"])
        self.assertEqual(by_part["Table — Legs"], ["CTN-006", "CTN-007"])

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

    def test_a_carton_without_dimensions_is_blocked(self):
        """Regression: blank dimensions used to save cleanly and declare 0 CBM."""
        self.client.post(self.url("auto-pack"))
        read = self.client.get(self.url("packing"))

        payload = self.payload(read.data["cartons"])
        for carton in payload["cartons"]:
            carton["length_in"] = carton["width_in"] = carton["height_in"] = None

        response = self.client.put(self.url("packing"), payload, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertTrue(
            any(b["code"] == "missing_dimensions" for b in response.data["blockers"])
        )

    def test_cannot_mark_packed_while_blocked(self):
        response = self.client.post(self.url("advance-status"))
        self.assertEqual(response.status_code, 200)  # draft -> packing

        response = self.client.post(self.url("advance-status"))
        self.assertEqual(response.status_code, 400)  # packing -> packed is gated


class PackingListTests(OrderFixture):
    """The Excel document the shipping desk sends out."""

    # Column positions, as the sheet lays them out.
    RANGE, COUNT, STYLE, COLOR, DESCRIPTION = 0, 1, 2, 3, 4
    QTY, TOTAL_QTY = 5, 6
    NET, TOTAL_NET, GROSS, TOTAL_GROSS = 7, 8, 9, 10
    LENGTH, WIDTH, HEIGHT, CBM, TOTAL_CBM = 11, 12, 13, 14, 15

    def rows(self):
        """Data rows only — between the column headers and the totals."""
        response = self.client.get(self.url("packing-list"))
        self.assertEqual(response.status_code, 200)

        sheet = load_workbook(BytesIO(b"".join(response.streaming_content))).active
        values = list(sheet.iter_rows(values_only=True))
        start = next(i for i, row in enumerate(values) if row[0] == "Carton Nos") + 1

        found = []
        for row in values[start:]:
            if row[0] and str(row[0]).startswith("TOTAL"):
                break
            found.append(row)
        return found

    def repack(self, edit):
        """Auto-pack, let `edit` change the plan, then save it back."""
        self.client.post(self.url("auto-pack"))
        cartons = self.client.get(self.url("packing")).data["cartons"]
        edit(cartons)
        response = self.client.put(self.url("packing"), self.payload(cartons), format="json")
        self.assertEqual(response.status_code, 200, response.data)

    def test_it_needs_cartons_before_there_is_anything_to_list(self):
        response = self.client.get(self.url("packing-list"))
        self.assertEqual(response.status_code, 400)

    def test_identical_cartons_collapse_to_one_row(self):
        self.client.post(self.url("auto-pack"))
        rows = self.rows()

        # Seven cartons, but only three different things in them: the chairs,
        # the table tops and the leg sets.
        self.assertEqual(self.order.cartons.count(), 7)
        self.assertEqual(len(rows), 3)

        self.assertEqual(
            [row[self.DESCRIPTION] for row in rows],
            ["Chair", "Table — Top", "Table — Legs"],
        )

    def test_a_row_names_its_carton_range_and_counts_them(self):
        self.client.post(self.url("auto-pack"))
        chairs = self.rows()[0]

        self.assertEqual(chairs[self.RANGE], "CTN-001 – CTN-003")
        self.assertEqual(chairs[self.COUNT], 3)

    def test_each_part_gets_one_unbroken_range(self):
        self.order.lines.filter(product=self.table).update(quantity=4)
        self.client.post(self.url("auto-pack"))
        tops, legs = self.rows()[1], self.rows()[2]

        self.assertEqual(tops[self.RANGE], "CTN-004 – CTN-007")
        self.assertEqual(legs[self.RANGE], "CTN-008 – CTN-011")

    def test_a_hand_edited_plan_with_gaps_names_every_run(self):
        """Nothing is abbreviated away: each number a row covers is either
        printed or inside a printed run."""
        def renumber(cartons):
            # Push the third chair carton clear of the first two.
            cartons[2]["carton_no"] = "CTN-009"

        self.repack(renumber)
        chairs = self.rows()[0]

        self.assertEqual(chairs[self.RANGE], "CTN-001 – CTN-002, CTN-009")
        self.assertEqual(chairs[self.COUNT], 3)

    def test_totals_multiply_the_per_carton_figures(self):
        self.client.post(self.url("auto-pack"))
        chairs = self.rows()[0]
        carton = self.order.cartons.first()

        self.assertEqual(chairs[self.QTY], 2)
        self.assertEqual(chairs[self.TOTAL_QTY], 6)
        self.assertEqual(Decimal(str(chairs[self.GROSS])), carton.gross_weight_kg)
        self.assertEqual(
            Decimal(str(chairs[self.TOTAL_GROSS])), carton.gross_weight_kg * 3
        )
        self.assertEqual(Decimal(str(chairs[self.TOTAL_CBM])), carton.cbm * 3)

    def test_a_row_carries_the_box_size_and_the_order_colour(self):
        self.client.post(self.url("auto-pack"))
        rows = self.rows()
        carton = self.order.cartons.first()

        self.assertEqual(
            [rows[0][self.LENGTH], rows[0][self.WIDTH], rows[0][self.HEIGHT]],
            [carton.length_in, carton.width_in, carton.height_in],
        )

        colors = {row[self.STYLE]: row[self.COLOR] for row in rows}
        self.assertEqual(colors["CHR-01"], "Charcoal Wash")
        self.assertEqual(colors["TBL-01"], "Natural Oak")

    def test_a_carton_weighed_differently_gets_its_own_row(self):
        """The whole point of collapsing is that the merged cartons really
        are identical — one reweighed box has to break out."""
        def heavier(cartons):
            cartons[0]["gross_weight_kg"] = "13.400"

        self.repack(heavier)
        rows = self.rows()

        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0][self.RANGE], "CTN-001")
        self.assertEqual(rows[0][self.COUNT], 1)
        self.assertEqual(rows[1][self.RANGE], "CTN-002 – CTN-003")
        self.assertEqual(rows[1][self.COUNT], 2)

    def test_the_filename_names_the_order(self):
        self.client.post(self.url("auto-pack"))
        response = self.client.get(self.url("packing-list"))
        self.assertIn(
            f"packing-list-{self.order.number}.xlsx", response["Content-Disposition"]
        )
