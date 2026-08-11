from decimal import Decimal

from django.test import TestCase
from rest_framework.test import APITestCase

from apps.masters.models import Merchant

from . import services
from .models import (
    DisplayOrder,
    DisplayOrderLine,
    DisplayProduct,
    DisplayProductPart,
    PackTemplate,
    PackTemplateItem,
)


def product(style_no, weight, size):
    length, width, height = size
    return DisplayProduct.objects.create(
        style_no=style_no,
        description=style_no,
        product_weight_kg=Decimal(str(weight)),
        length_in=Decimal(str(length)),
        width_in=Decimal(str(width)),
        height_in=Decimal(str(height)),
    )


def template(code, items, box=(28, 20, 16), box_kg=0.8, packing_kg=0.25):
    length, width, height = box
    tpl = PackTemplate.objects.create(
        code=code,
        name=code,
        box_length_in=Decimal(str(length)),
        box_width_in=Decimal(str(width)),
        box_height_in=Decimal(str(height)),
        box_weight_kg=Decimal(str(box_kg)),
        packing_material_weight_kg=Decimal(str(packing_kg)),
        is_library=True,
    )
    for prod, quantity in items:
        PackTemplateItem.objects.create(template=tpl, product=prod, quantity=quantity)
    return tpl


class DisplayPackingTests(TestCase):
    def setUp(self):
        self.merchant = Merchant.objects.create(code="TRN", name="Terrain Home")

        self.bow = product("DSP-BOW-12", 0.08, (12, 12, 4))
        self.orn = product("DSP-ORN-06", 0.55, (9, 6, 3))
        self.wrt = product("DSP-WRT-24", 1.20, (24, 24, 5))
        self.grl = product("DSP-GRL-72", 0.90, (14, 10, 8))

        self.order = DisplayOrder.objects.create(name="Holiday", merchant=self.merchant)
        for prod, quantity in (
            (self.bow, 840),
            (self.orn, 96),
            (self.wrt, 140),
            (self.grl, 158),
        ):
            DisplayOrderLine.objects.create(
                order=self.order, product=prod, quantity=quantity
            )

        self.t1 = template(
            "TPL-001",
            [(self.bow, 30), (self.wrt, 5)],
            box=(44, 32, 32),
            box_kg=1.6,
            packing_kg=0.5,
        )
        self.t2 = template(
            "TPL-002",
            [(self.orn, 12), (self.grl, 6)],
            box=(30, 20, 20),
            box_kg=0.9,
            packing_kg=0.6,
        )
        self.t3 = template("TPL-003", [(self.grl, 6)])
        self.t4 = template(
            "TPL-004", [(self.wrt, 10)], box=(42, 30, 30), box_kg=1.5, packing_kg=0.5
        )

    # ── The wall ─────────────────────────────────────────────────────

    def test_max_applications_takes_the_scarcest_product(self):
        """12 per box against 96 ornament sets allows 8; the garlands allow 26."""
        remaining = services.remaining_quantities(self.order)
        self.assertEqual(services.max_applications(self.t2, remaining), 8)

    def test_template_with_no_items_never_applies(self):
        empty = PackTemplate.objects.create(code="TPL-EMPTY", name="empty")
        remaining = services.remaining_quantities(self.order)
        self.assertEqual(services.max_applications(empty, remaining), 0)

    # ── The loop ─────────────────────────────────────────────────────

    def test_the_worked_example(self):
        """ARCHITECTURE.md §10.2, end to end."""
        for tpl, count in ((self.t1, 28), (self.t2, 8), (self.t3, 18)):
            step = services.apply_step(self.order, tpl)
            self.assertEqual(step.count, count, f"{tpl.code} applied {step.count}")

        self.assertEqual(services.remaining_quantities(self.order), {self.grl.id: 2})

        tail = template("TPL-TAIL", [(self.grl, 2)], box=(20, 14, 12))
        services.apply_step(self.order, tail)

        self.assertEqual(services.remaining_quantities(self.order), {})
        self.assertEqual(self.order.cartons.count(), 55)
        self.assertEqual(services.find_blockers(self.order), [])
        self.assertTrue(all(row.is_matched for row in services.reconcile(self.order)))

    def test_a_count_above_capacity_is_refused(self):
        with self.assertRaises(services.PackingError):
            services.apply_step(self.order, self.t1, count=29)

    def test_a_template_that_does_not_fit_is_refused(self):
        services.apply_step(self.order, self.t1)  # 28, takes every wreath
        with self.assertRaises(services.PackingError):
            services.apply_step(self.order, self.t4)

    # ── Cartons ──────────────────────────────────────────────────────

    def test_carton_weights_come_from_contents(self):
        services.apply_step(self.order, self.t1, count=1)
        carton = self.order.cartons.get()

        # 30 x 0.08 + 5 x 1.20 = 8.4, plus 0.5 packing, plus 1.6 box.
        self.assertEqual(carton.net_weight_kg, Decimal("8.900"))
        self.assertEqual(carton.gross_weight_kg, Decimal("10.500"))
        self.assertEqual(carton.contents.count(), 2)

    def test_carton_numbers_run_on_across_steps(self):
        services.apply_step(self.order, self.t1, count=2)
        services.apply_step(self.order, self.t2, count=2)
        self.assertEqual(
            list(self.order.cartons.values_list("carton_no", flat=True)),
            ["CTN-001", "CTN-002", "CTN-003", "CTN-004"],
        )

    def test_earlier_carton_numbers_survive_a_later_edit(self):
        """A number already written on a box must not move."""
        services.apply_step(self.order, self.t1, count=2)
        services.apply_step(self.order, self.t2, count=2)
        services.recount_step(self.order, 2, 1)

        self.assertEqual(
            list(
                self.order.cartons.filter(step__sequence=1).values_list(
                    "carton_no", flat=True
                )
            ),
            ["CTN-001", "CTN-002"],
        )

    # ── Editing the plan ─────────────────────────────────────────────

    def test_recount_clamps_a_starved_later_step_and_reports_it(self):
        small = DisplayOrder.objects.create(name="Small", merchant=self.merchant)
        DisplayOrderLine.objects.create(order=small, product=self.bow, quantity=10)
        a = template("TPL-A", [(self.bow, 5)])
        b = template("TPL-B", [(self.bow, 5)])

        services.apply_step(small, a, count=1)
        services.apply_step(small, b, count=1)

        adjustments = services.recount_step(small, 1, 2)

        self.assertEqual(len(adjustments), 1)
        self.assertEqual((adjustments[0].template_code, adjustments[0].now), ("TPL-B", 0))
        self.assertEqual(small.steps.count(), 1)
        self.assertEqual(services.remaining_quantities(small), {})

    def test_deleting_a_step_closes_the_gap_in_the_sequence(self):
        services.apply_step(self.order, self.t1, count=1)
        services.apply_step(self.order, self.t2, count=1)
        services.apply_step(self.order, self.t3, count=1)

        services.delete_step(self.order, 2)

        self.assertEqual(
            list(self.order.steps.values_list("sequence", "template__code")),
            [(1, "TPL-001"), (2, "TPL-003")],
        )

    def test_deleting_a_step_returns_its_units_to_the_remainder(self):
        services.apply_step(self.order, self.t2, count=8)
        before = services.remaining_quantities(self.order)[self.grl.id]
        services.delete_step(self.order, 1)
        after = services.remaining_quantities(self.order)[self.grl.id]
        self.assertEqual(after - before, 48)

    # ── Reconciliation, blockers, warnings ───────────────────────────

    def test_an_unpacked_remainder_blocks(self):
        services.apply_step(self.order, self.t1, count=1)
        codes = {blocker.code for blocker in services.find_blockers(self.order)}
        self.assertIn("quantity_mismatch", codes)

    def test_a_carton_missing_dimensions_blocks(self):
        services.apply_step(self.order, self.t1, count=1)
        self.order.cartons.update(width_in=None)
        codes = {blocker.code for blocker in services.find_blockers(self.order)}
        self.assertIn("missing_dimensions", codes)

    def test_gross_below_net_blocks(self):
        services.apply_step(self.order, self.t1, count=1)
        self.order.cartons.update(gross_weight_kg=Decimal("1.000"))
        codes = {blocker.code for blocker in services.find_blockers(self.order)}
        self.assertIn("gross_below_net", codes)

    def test_a_mostly_empty_box_warns_but_does_not_block(self):
        roomy = template("TPL-AIR", [(self.bow, 1)], box=(40, 40, 40))
        services.apply_step(self.order, roomy, count=1)

        codes = {warning.code for warning in services.find_warnings(self.order)}
        self.assertIn("poor_fill", codes)
        self.assertNotIn(
            "poor_fill", {b.code for b in services.find_blockers(self.order)}
        )

    def test_overfilling_a_carton_warns_but_does_not_block(self):
        services.apply_step(self.order, self.t3, count=1)
        content = self.order.cartons.get().contents.get()
        content.quantity = 8  # template holds 6
        content.save()

        codes = {warning.code for warning in services.find_warnings(self.order)}
        self.assertIn("template_capacity_exceeded", codes)

    # ── The picker ───────────────────────────────────────────────────

    def test_only_templates_that_still_fit_are_offered(self):
        services.apply_step(self.order, self.t1)
        services.apply_step(self.order, self.t2)
        services.apply_step(self.order, self.t3)

        self.assertEqual(services.applicable_templates(self.order), [])

    def test_a_one_off_is_offered_on_the_order_it_was_written_for(self):
        """Saving a tail-filler that then never appears is the same as losing it."""
        tail = template("TPL-TAIL", [(self.grl, 1)])
        tail.is_library = False
        tail.order = self.order
        tail.save()

        offered = {row["code"] for row in services.applicable_templates(self.order)}
        self.assertIn("TPL-TAIL", offered)

    def test_a_one_off_stays_off_every_other_order(self):
        tail = template("TPL-TAIL", [(self.grl, 1)])
        tail.is_library = False
        tail.order = self.order
        tail.save()

        other = DisplayOrder.objects.create(name="Other", merchant=self.merchant)
        DisplayOrderLine.objects.create(order=other, product=self.grl, quantity=50)

        offered = {row["code"] for row in services.applicable_templates(other)}
        self.assertNotIn("TPL-TAIL", offered)

    def test_another_merchants_template_is_not_offered(self):
        other = Merchant.objects.create(code="WE", name="West Elm")
        mine = template("TPL-MINE", [(self.grl, 1)])
        mine.merchant = other
        mine.save()

        offered = {row["code"] for row in services.applicable_templates(self.order)}
        self.assertNotIn("TPL-MINE", offered)

    # ── Remaining follows the cartons, not the steps ─────────────────

    def test_a_hand_edited_carton_moves_the_remainder(self):
        services.apply_step(self.order, self.t1, count=1)
        before = services.remaining_quantities(self.order)[self.bow.id]

        carton = self.order.cartons.get()
        content = carton.contents.get(product=self.bow)
        content.quantity += 5
        content.save()

        after = services.remaining_quantities(self.order)[self.bow.id]
        self.assertEqual(before - after, 5)


class DisplayOrderNumberTests(TestCase):
    def test_numbers_run_sequentially_within_the_year(self):
        merchant = Merchant.objects.create(code="TRN", name="Terrain Home")
        first = DisplayOrder.objects.create(name="One", merchant=merchant)
        second = DisplayOrder.objects.create(name="Two", merchant=merchant)

        self.assertTrue(first.number.startswith("DP-"))
        self.assertEqual(int(second.number[-4:]) - int(first.number[-4:]), 1)


class DisplayProductShapeTests(APITestCase):
    """A display product is either one piece or several parts, fixed at birth."""

    URL = "/api/display-products/"

    def payload(self, **overrides):
        body = {
            "style_no": "DSP-WRT-24",
            "description": '24" Pine Wreath',
            "is_multi_part": True,
            "parts": [
                {"name": "Frame", "product_weight_kg": "0.400", "sort_order": 0},
                {"name": "Trim", "product_weight_kg": "0.150", "sort_order": 1},
            ],
        }
        body.update(overrides)
        return body

    def test_a_multi_part_product_saves_its_parts(self):
        response = self.client.post(self.URL, self.payload(), format="json")

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual([part["name"] for part in response.data["parts"]],
                         ["Frame", "Trim"])

    def test_a_multi_part_product_carries_no_figures_of_its_own(self):
        """Its parts are what get weighed and boxed; the whole never is."""
        response = self.client.post(
            self.URL, self.payload(product_weight_kg="0.550"), format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("product_weight_kg", response.data)

    def test_a_single_piece_product_cannot_have_parts(self):
        response = self.client.post(
            self.URL, self.payload(is_multi_part=False), format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("parts", response.data)

    def test_two_parts_are_the_minimum(self):
        body = self.payload()
        body["parts"] = body["parts"][:1]
        response = self.client.post(self.URL, body, format="json")

        self.assertEqual(response.status_code, 400)
        self.assertIn("parts", response.data)

    def test_shape_cannot_change_after_creation(self):
        created = self.client.post(self.URL, self.payload(), format="json").data

        response = self.client.patch(
            f"{self.URL}{created['id']}/", {"is_multi_part": False}, format="json"
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("is_multi_part", response.data)

    def test_editing_parts_keeps_their_rows(self):
        """A recreated part would orphan every template item aimed at it."""
        created = self.client.post(self.URL, self.payload(), format="json").data
        ids = [part["id"] for part in created["parts"]]

        response = self.client.patch(
            f"{self.URL}{created['id']}/",
            {
                "parts": [
                    {"id": ids[0], "name": "Wire frame", "sort_order": 0},
                    {"id": ids[1], "name": "Trim", "sort_order": 1},
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual([part["id"] for part in response.data["parts"]], ids)
        self.assertEqual(response.data["parts"][0]["name"], "Wire frame")

    def test_a_part_dropped_from_the_payload_is_deleted(self):
        created = self.client.post(self.URL, self.payload(), format="json").data
        ids = [part["id"] for part in created["parts"]]

        self.client.patch(
            f"{self.URL}{created['id']}/",
            {
                "parts": [
                    {"id": ids[0], "name": "Frame", "sort_order": 0},
                    {"name": "Bow", "sort_order": 1},
                ]
            },
            format="json",
        )

        self.assertEqual(DisplayProductPart.objects.filter(pk=ids[1]).count(), 0)
