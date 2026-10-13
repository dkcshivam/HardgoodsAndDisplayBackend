import base64
import tempfile
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.test import TestCase, override_settings

from apps.catalog.models import Product
from apps.common.testing import SignedInAPITestCase, local_storage, make_user
from apps.display import services as display_services
from apps.display.models import (
    DisplayOrder,
    DisplayOrderLine,
    DisplayProduct,
    PackTemplate,
    PackTemplateItem,
)
from apps.masters.models import Merchant, Store
from apps.orders.models import Order, OrderLine

from .models import Action, AppendOnlyError, AuditEvent

PIXEL_GIF = base64.b64decode(
    b"R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw=="
)


def event(**fields):
    return AuditEvent.objects.create(
        **{
            "action": Action.UPDATE,
            "target_type": "masters.category",
            "target_id": "1",
            "target_repr": "Lighting",
            "changes": {"name": ["Lamps", "Lighting"]},
            **fields,
        }
    )


def part(**overrides):
    return {
        "name": "Top",
        "box_length_in": "20.00",
        "box_width_in": "14.00",
        "box_height_in": "6.00",
        "product_weight_kg": "4.000",
        "packing_material_weight_kg": "0.200",
        "box_weight_kg": "0.500",
        "sort_order": 0,
        **overrides,
    }


def chair():
    return Product.objects.create(
        style_no="CHR-01",
        description="Chair",
        pack_per_box=2,
        box_length_in=40,
        box_width_in=30,
        box_height_in=24,
        product_weight_kg=Decimal("6"),
        box_weight_kg=Decimal("0.5"),
        packing_material_weight_kg=Decimal("0.2"),
    )


def merchant():
    return Merchant.objects.get_or_create(code="UO", defaults={"name": "UO"})[0]


def display_product(style_no="DSP-BOW-12"):
    return DisplayProduct.objects.create(
        style_no=style_no,
        description=style_no,
        product_weight_kg=Decimal("0.08"),
        length_in=12,
        width_in=12,
        height_in=4,
    )


def display_template(code, product, quantity):
    template = PackTemplate.objects.create(
        code=code,
        name=code,
        box_length_in=28,
        box_width_in=20,
        box_height_in=16,
        box_weight_kg=Decimal("0.8"),
        packing_material_weight_kg=Decimal("0.25"),
        is_library=True,
    )
    PackTemplateItem.objects.create(template=template, product=product, quantity=quantity)
    return template


class AppendOnlyTests(TestCase):
    def setUp(self):
        self.event = event(actor=make_user(username="asha"), actor_name="asha")

    def assertUnchanged(self):
        stored = AuditEvent.objects.get(pk=self.event.pk)
        self.assertEqual(stored.target_repr, "Lighting")
        self.assertEqual(stored.changes, {"name": ["Lamps", "Lighting"]})

    def test_the_model_refuses_to_change_or_delete_an_event(self):
        self.event.target_repr = "Something else"
        with self.assertRaises(AppendOnlyError):
            self.event.save()
        with self.assertRaises(AppendOnlyError):
            self.event.delete()
        with self.assertRaises(AppendOnlyError):
            AuditEvent.objects.filter(pk=self.event.pk).update(target_repr="x")
        with self.assertRaises(AppendOnlyError):
            AuditEvent.objects.all().delete()
        self.assertUnchanged()

    def test_the_database_refuses_to_change_or_delete_an_event(self):
        for sql in (
            "UPDATE audit_auditevent SET target_repr = 'x' WHERE id = %s",
            "DELETE FROM audit_auditevent WHERE id = %s",
        ):
            with self.subTest(sql=sql.split()[0]):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute(sql, [self.event.pk])
        self.assertUnchanged()

    def test_the_database_refuses_an_unknown_action(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            event(action="erase")

    def test_an_actor_with_events_cannot_be_deleted(self):
        with self.assertRaises(ProtectedError):
            self.event.actor.delete()


class AuditedTestCase(SignedInAPITestCase):
    def events(self, action=None):
        events = AuditEvent.objects.order_by("id")
        return list(events.filter(action=action) if action else events)

    def only_event(self, action=None):
        events = self.events(action)
        self.assertEqual(len(events), 1, [(e.action, e.changes) for e in events])
        return events[0]


class CrudTests(AuditedTestCase):
    def test_a_category_is_recorded_from_create_to_delete(self):
        pk = self.client.post(
            "/api/categories/", {"name": "Lighting"}, format="json"
        ).data["id"]
        self.client.patch(f"/api/categories/{pk}/", {"name": "Lamps"}, format="json")
        self.client.delete(f"/api/categories/{pk}/")

        created, updated, deleted = self.events()
        self.assertEqual(
            [(e.action, e.target_type, e.target_id, e.target_repr) for e in self.events()],
            [
                ("create", "masters.category", str(pk), "Lighting"),
                ("update", "masters.category", str(pk), "Lamps"),
                ("delete", "masters.category", str(pk), "Lamps"),
            ],
        )
        self.assertEqual(
            created.changes, {"name": [None, "Lighting"], "is_active": [None, True]}
        )
        self.assertEqual(updated.changes, {"name": ["Lighting", "Lamps"]})
        self.assertEqual(
            deleted.changes, {"name": ["Lamps", None], "is_active": [True, None]}
        )
        self.assertEqual(created.actor, self.user)
        self.assertEqual(created.actor_name, self.user.username)

    def test_the_actor_is_named_as_they_were_called_at_the_time(self):
        self.user.first_name, self.user.last_name = "Asha", "Rao"
        self.user.save()
        self.client.post("/api/categories/", {"name": "Lighting"}, format="json")
        self.assertEqual(self.only_event().actor_name, "Asha Rao")

    def product(self):
        return self.client.post(
            "/api/products/",
            {
                "style_no": "TBL-01",
                "description": "Table",
                "is_multi_part": True,
                "parts": [part(), part(name="Legs", sort_order=1)],
            },
            format="json",
        ).data

    def test_a_product_and_its_parts_are_recorded(self):
        product = self.product()

        created = self.only_event()
        self.assertEqual(created.target_type, "catalog.product")
        self.assertEqual(created.target_repr, "TBL-01")
        self.assertEqual(created.changes["style_no"], [None, "TBL-01"])
        self.assertNotIn("created_at", created.changes)
        before, after = created.changes["parts"]
        self.assertIsNone(before)
        self.assertEqual(sorted(row["name"] for row in after), ["Legs", "Top"])

        self.client.delete(f"/api/products/{product['id']}/")

        deleted = self.only_event(Action.DELETE)
        self.assertEqual(deleted.target_id, str(product["id"]))
        self.assertEqual(deleted.target_repr, "TBL-01")
        self.assertEqual(deleted.changes["style_no"], ["TBL-01", None])
        before, after = deleted.changes["parts"]
        self.assertEqual(len(before), 2)
        self.assertIsNone(after)

    def test_editing_only_a_products_parts_is_an_update(self):
        product = self.product()
        top, legs = product["parts"]

        response = self.client.patch(
            f"/api/products/{product['id']}/",
            {
                "parts": [
                    part(id=top["id"], product_weight_kg="5.000"),
                    part(id=legs["id"], name="Legs", sort_order=1),
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        changes = self.only_event(Action.UPDATE).changes
        self.assertEqual(list(changes), ["parts"])
        # Only the part that changed, as it was and as it is.
        [before], [after] = changes["parts"]
        self.assertEqual((before["name"], before["product_weight_kg"]), ("Top", "4.000"))
        self.assertEqual((after["name"], after["product_weight_kg"]), ("Top", "5.000"))
        self.assertNotIn("id", after)

    def test_a_refused_delete_records_nothing(self):
        product = chair()
        order = Order.objects.create(name="Fall", merchant=merchant())
        OrderLine.objects.create(order=order, product=product, quantity=2)

        response = self.client.delete(f"/api/products/{product.pk}/")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.events(), [])

    def order_payload(self, product):
        return {
            "name": "Fall dining",
            "merchant": merchant().pk,
            "buyer_name": "UO Buying",
            "shipping_address": {"country": "US", "city": "Philadelphia"},
            "lines": [{"product": product.pk, "quantity": 6, "color": "Oak"}],
        }

    def test_an_order_its_lines_and_its_address_are_recorded(self):
        product = chair()
        order = self.client.post(
            "/api/orders/", self.order_payload(product), format="json"
        ).data

        created = self.only_event()
        self.assertEqual(created.target_type, "orders.order")
        self.assertEqual(created.target_repr, order["number"])
        self.assertEqual(
            created.changes["lines"],
            [None, [{"product": product.pk, "quantity": 6, "color": "Oak"}]],
        )

        url = f"/api/orders/{order['id']}/"
        line = {"product": product.pk, "quantity": 8, "color": "Oak"}
        self.client.patch(url, {"lines": [line]}, format="json")
        self.client.patch(
            url, {"shipping_address": {"country": "US", "city": "Boston"}}, format="json"
        )
        self.client.delete(url)

        lines, address = self.events(Action.UPDATE)
        self.assertEqual(
            lines.changes,
            {
                "lines": [
                    [{"product": product.pk, "quantity": 6, "color": "Oak"}],
                    [{"product": product.pk, "quantity": 8, "color": "Oak"}],
                ]
            },
        )
        self.assertEqual(address.changes, {"ship_city": ["Philadelphia", "Boston"]})
        deleted = self.only_event(Action.DELETE)
        self.assertEqual(deleted.changes["number"], [order["number"], None])

    def test_an_update_that_changes_nothing_records_nothing(self):
        category = self.client.post(
            "/api/categories/", {"name": "Lighting"}, format="json"
        ).data
        product = self.product()
        order_product = chair()
        order = self.client.post(
            "/api/orders/", self.order_payload(order_product), format="json"
        ).data
        before = self.events()

        self.client.patch(
            f"/api/categories/{category['id']}/", {"name": "Lighting"}, format="json"
        )
        # Parts sent without their ids are recreated: new rows, same parts.
        response = self.client.put(
            f"/api/products/{product['id']}/",
            {
                "style_no": "TBL-01",
                "description": "Table",
                "is_multi_part": True,
                "parts": [part(), part(name="Legs", sort_order=1)],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        # And lines are rewritten on every save.
        response = self.client.put(
            f"/api/orders/{order['id']}/", self.order_payload(order_product), format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)

        self.assertEqual(self.events(), before)

    def test_editing_only_a_templates_items_is_an_update(self):
        bow = display_product()
        template = display_template("T-001", bow, 10)

        response = self.client.patch(
            f"/api/pack-templates/{template.pk}/",
            {"items": [{"product": bow.pk, "quantity": 5}]},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)

        event = self.only_event()
        self.assertEqual(event.target_type, "display.packtemplate")
        self.assertEqual(
            event.changes,
            {
                "items": [
                    [{"product": bow.pk, "quantity": 10}],
                    [{"product": bow.pk, "quantity": 5}],
                ]
            },
        )

    def test_a_display_order_edit_records_the_status_it_knocks_back(self):
        bow, wreath = display_product(), display_product("DSP-WRT-24")
        outlet = Store.objects.create(name="118 Portland")
        order = DisplayOrder.objects.create(name="Holiday", merchant=merchant())
        DisplayOrderLine.objects.create(
            order=order, store=outlet, product=bow, quantity=10, store_position=1
        )
        display_services.apply_step(order, display_template("T-001", bow, 10), outlet)
        DisplayOrder.objects.filter(pk=order.pk).update(status="packed")

        response = self.client.patch(
            f"/api/display-orders/{order.pk}/",
            {
                "lines": [
                    {"store": outlet.pk, "product": bow.pk, "quantity": 10},
                    {"store": outlet.pk, "product": wreath.pk, "quantity": 4},
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["status"], "packing")

        changes = self.only_event().changes
        self.assertEqual(changes["status"], ["packed", "packing"])
        self.assertEqual(
            changes["lines"],
            [
                [],
                [
                    {
                        "store": outlet.pk,
                        "product": wreath.pk,
                        "quantity": 4,
                        "store_position": 1,
                    }
                ],
            ],
        )


@override_settings(STORAGES=local_storage(tempfile.mkdtemp()))
class PhotoTests(AuditedTestCase):
    def test_a_photo_is_recorded_when_added_and_when_removed(self):
        product = chair()
        photo = self.client.post(
            "/api/product-images/",
            {
                "product": product.pk,
                "image": SimpleUploadedFile("a.gif", PIXEL_GIF, content_type="image/gif"),
            },
            format="multipart",
        ).data
        self.client.delete(f"/api/product-images/{photo['id']}/")

        created, deleted = self.events()
        self.assertEqual(created.target_type, "catalog.productimage")
        self.assertEqual(created.changes["is_main"], [None, True])
        name = created.changes["image"][1]
        self.assertTrue(name.startswith(f"products/{product.pk}/"), name)
        self.assertEqual(deleted.action, Action.DELETE)
        self.assertEqual(deleted.changes["image"], [name, None])
