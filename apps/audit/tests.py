import base64
import json
import tempfile
from datetime import datetime
from decimal import Decimal
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from apps.accounts.models import Role
from apps.catalog.models import Product
from apps.common.testing import SignedInAPITestCase, local_storage, make_user, sign_in
from apps.display import services as display_services
from apps.display.models import (
    DisplayOrder,
    DisplayOrderLine,
    DisplayProduct,
    PackTemplate,
    PackTemplateItem,
)
from apps.masters.models import Category, Merchant, Store
from apps.masters.serializers import CategorySerializer
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


class HardgoodsActionTests(AuditedTestCase):
    def setUp(self):
        super().setUp()
        self.order = Order.objects.create(name="Fall", merchant=merchant())
        OrderLine.objects.create(order=self.order, product=chair(), quantity=6)
        self.url = f"/api/orders/{self.order.pk}/"

    def test_auto_pack_records_the_size_of_the_plan(self):
        plan = self.client.post(self.url + "auto-pack/").data

        event = self.only_event()
        self.assertEqual(
            (event.action, event.target_type, event.target_id, event.target_repr),
            ("auto_pack", "orders.order", str(self.order.pk), self.order.number),
        )
        self.assertEqual(
            event.changes,
            {
                "carton_count": [0, 3],
                "total_gross_weight_kg": ["0.000", str(plan["total_gross_weight_kg"])],
            },
        )

    def put_packing(self, cartons):
        return self.client.put(
            self.url + "packing/",
            {
                "cartons": [
                    {
                        "carton_no": carton["carton_no"],
                        "length_in": carton["length_in"],
                        "width_in": carton["width_in"],
                        "height_in": carton["height_in"],
                        "gross_weight_kg": carton["gross_weight_kg"],
                        "contents": [
                            {
                                "product": item["product"],
                                "quantity": item["quantity"],
                                "net_weight_kg": item["net_weight_kg"],
                            }
                            for item in carton["contents"]
                        ],
                    }
                    for carton in cartons
                ]
            },
            format="json",
        )

    def test_saving_the_packing_records_its_size_and_the_status_it_moved(self):
        plan = self.client.post(self.url + "auto-pack/").data
        weight = str(plan["total_gross_weight_kg"])

        # Two boxes of three leave chairs unpacked: refused, so not recorded.
        self.assertEqual(self.put_packing(plan["cartons"][:2]).status_code, 400)
        self.assertEqual(self.events(Action.SAVE_PACKING), [])

        self.assertEqual(self.put_packing(plan["cartons"]).status_code, 200)
        self.assertEqual(
            self.only_event(Action.SAVE_PACKING).changes,
            {
                "carton_count": [3, 3],
                "total_gross_weight_kg": [weight, weight],
                "status": ["draft", "packing"],
            },
        )

    def test_advancing_the_status_records_the_rung(self):
        self.assertEqual(self.client.post(self.url + "advance-status/").status_code, 200)
        # Packed needs a plan, and there is none: refused, so not recorded.
        self.assertEqual(self.client.post(self.url + "advance-status/").status_code, 400)

        event = self.only_event()
        self.assertEqual(event.action, Action.ADVANCE_STATUS)
        self.assertEqual(event.changes, {"status": ["draft", "packing"]})


class DisplayActionTests(AuditedTestCase):
    def setUp(self):
        super().setUp()
        self.bow = display_product()
        self.template = display_template("T-001", self.bow, 10)
        self.portland = Store.objects.create(name="118 Portland")
        self.austin = Store.objects.create(name="204 Austin")
        self.order = DisplayOrder.objects.create(name="Holiday", merchant=merchant())
        for position, outlet in enumerate((self.portland, self.austin), start=1):
            DisplayOrderLine.objects.create(
                order=self.order,
                store=outlet,
                product=self.bow,
                quantity=30,
                store_position=position,
            )
        self.url = f"/api/display-orders/{self.order.pk}/"

    def apply(self, outlet, **extra):
        return self.client.post(
            self.url + "steps/",
            {"template": self.template.pk, "store": outlet.pk, **extra},
            format="json",
        )

    def test_a_step_is_recorded_when_applied_recounted_and_removed(self):
        self.assertEqual(self.apply(self.portland).status_code, 200)
        self.assertEqual(
            self.client.patch(self.url + "steps/1/", {"count": 2}, format="json").status_code,
            200,
        )
        self.assertEqual(self.client.delete(self.url + "steps/1/").status_code, 200)

        added, changed, removed = self.events()
        self.assertEqual(
            [e.action for e in (added, changed, removed)],
            ["add_step", "update_step", "delete_step"],
        )
        self.assertEqual({e.target_repr for e in self.events()}, {self.order.number})
        self.assertEqual(
            added.changes,
            {
                "status": ["draft", "packing"],
                "sequence": [None, 1],
                "store": [None, "118 Portland"],
                "template": [None, "T-001"],
                "count": [None, 3],
            },
        )
        self.assertEqual(
            changed.changes,
            {
                "sequence": [1, 1],
                "store": ["118 Portland", "118 Portland"],
                "template": ["T-001", "T-001"],
                "count": [3, 2],
            },
        )
        self.assertEqual(
            removed.changes,
            {
                "sequence": [1, None],
                "store": ["118 Portland", None],
                "template": ["T-001", None],
                "count": [2, None],
            },
        )

    def test_a_refused_step_records_nothing(self):
        self.assertEqual(self.apply(self.portland, count=9).status_code, 400)
        self.assertEqual(self.client.delete(self.url + "steps/7/").status_code, 400)
        self.assertEqual(self.events(), [])

    def test_replicating_a_plan_is_one_event_naming_where_it_went(self):
        self.apply(self.portland)

        response = self.client.post(
            self.url + "replicate/", {"store": self.portland.pk}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.data)

        self.assertEqual(len(self.events(Action.ADD_STEP)), 1)
        self.assertEqual(
            self.only_event(Action.REPLICATE).changes,
            {"store": [None, "118 Portland"], "replicated_to": [None, ["204 Austin"]]},
        )

    def test_advancing_the_status_records_the_rung(self):
        self.client.post(self.url + "advance-status/")
        event = self.only_event()
        self.assertEqual(event.target_type, "display.displayorder")
        self.assertEqual(event.changes, {"status": ["draft", "packing"]})


class FailedRequestTests(AuditedTestCase):
    def test_a_request_that_fails_after_its_write_leaves_no_event(self):
        category = Category.objects.create(name="Lighting")
        self.client.raise_request_exception = False

        with (
            mock.patch.object(
                CategorySerializer, "to_representation", side_effect=RuntimeError
            ),
            self.assertLogs("django.request", "ERROR"),
        ):
            response = self.client.patch(
                f"/api/categories/{category.pk}/", {"name": "Lamps"}, format="json"
            )

        self.assertEqual(response.status_code, 500)
        category.refresh_from_db()
        self.assertEqual(category.name, "Lighting")
        self.assertEqual(self.events(), [])


class UserTests(AuditedTestCase):
    role = Role.ADMIN

    def test_creating_a_user_is_recorded_without_the_password(self):
        response = self.client.post(
            "/api/users/",
            {
                "username": "asha",
                "first_name": "Asha",
                "role": "senior_merchant",
                "password": "a-long-pass-123",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.data)

        event = self.only_event()
        self.assertEqual(
            (event.action, event.actor, event.target_type, event.target_id, event.target_repr),
            ("create", self.user, "auth.user", str(response.data["id"]), "asha"),
        )
        self.assertEqual(event.changes["username"], [None, "asha"])
        self.assertEqual(event.changes["role"], [None, "senior_merchant"])
        self.assertEqual(event.changes["password"], [None, "***"])
        recorded = json.dumps(event.changes)
        self.assertNotIn("a-long-pass-123", recorded)
        self.assertNotIn(get_user_model().objects.get(username="asha").password, recorded)

    def test_editing_a_user_is_recorded_and_a_new_password_masked(self):
        user = make_user(username="asha")
        url = f"/api/users/{user.pk}/"

        self.client.patch(url, {"role": "senior_merchant", "first_name": "Asha"}, format="json")
        self.client.patch(url, {"password": "a-new-long-pass-456"}, format="json")
        # A blank password keeps the old one: nothing changed, nothing recorded.
        self.client.patch(url, {"first_name": "Asha", "password": ""}, format="json")

        role, password = self.events()
        self.assertEqual(
            role.changes,
            {"first_name": ["", "Asha"], "role": ["merchant", "senior_merchant"]},
        )
        self.assertEqual(password.changes, {"password": ["***", "***"]})
        self.assertEqual({role.target_repr, password.target_repr}, {"asha"})

    def test_changing_your_own_password_is_recorded_masked(self):
        response = self.client.post(
            "/api/auth/password/",
            {"current_password": "a-long-pass-123", "new_password": "a-new-long-pass-456"},
            format="json",
        )
        self.assertEqual(response.status_code, 204)

        event = self.only_event()
        self.assertEqual(
            (event.action, event.actor, event.target_type, event.target_id),
            ("update", self.user, "auth.user", str(self.user.pk)),
        )
        self.assertEqual(event.changes, {"password": ["***", "***"]})


class SessionTests(APITestCase):
    def setUp(self):
        # The login throttle counts in the cache, which outlives a test.
        cache.clear()
        self.user = make_user(username="asha", first_name="Asha", last_name="Rao")

    def login(self, password="a-long-pass-123"):
        return self.client.post(
            "/api/auth/login/", {"username": "asha", "password": password}, format="json"
        )

    def test_a_login_and_a_logout_are_recorded_against_the_user(self):
        tokens = self.login().data
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        response = self.client.post(
            "/api/auth/logout/", {"refresh": tokens["refresh"]}, format="json"
        )
        self.assertEqual(response.status_code, 204)

        events = AuditEvent.objects.order_by("id")
        self.assertEqual(
            [
                (e.action, e.actor, e.actor_name, e.target_type, e.target_id, e.changes)
                for e in events
            ],
            [
                (action, self.user, "Asha Rao", "auth.user", str(self.user.pk), {})
                for action in ("login", "logout")
            ],
        )

    def test_a_failed_login_is_not_recorded(self):
        self.assertEqual(self.login("not-the-password").status_code, 401)
        self.assertFalse(AuditEvent.objects.exists())


class EndpointTests(AuditedTestCase):
    role = Role.ADMIN
    URL = "/api/audit-events/"

    def ids(self, query=None):
        response = self.client.get(self.URL, query or {})
        self.assertEqual(response.status_code, 200, response.data)
        return [row["id"] for row in response.data["results"]]

    def test_only_an_admin_may_read_the_trail(self):
        for role in (Role.MERCHANT, Role.SENIOR_MERCHANT):
            with self.subTest(role=role):
                client = APIClient()
                sign_in(client, role)
                self.assertEqual(client.get(self.URL).status_code, 403)
        self.assertEqual(APIClient().get(self.URL).status_code, 401)

    def test_an_event_reads_as_the_contract_has_it(self):
        self.client.post("/api/categories/", {"name": "Lighting"}, format="json")

        response = self.client.get(self.URL)
        self.assertEqual(response.data["count"], 1)
        row = response.data["results"][0]
        self.assertEqual(
            {key: value for key, value in row.items() if key not in ("id", "created_at")},
            {
                "actor": self.user.pk,
                "actor_name": self.user.username,
                "action": "create",
                "action_label": "Created",
                "target_type": "masters.category",
                "target_label": "Category",
                "target_id": str(Category.objects.get().pk),
                "target_repr": "Lighting",
                "changes": {"name": [None, "Lighting"], "is_active": [None, True]},
            },
        )
        self.assertTrue(row["created_at"].endswith("+05:30"), row["created_at"])
        self.assertEqual(self.client.get(f"{self.URL}{row['id']}/").data, row)

    def test_the_target_label_is_the_models_name(self):
        for target_type, label in (
            ("orders.order", "Order"),
            ("display.displayproduct", "Display Product"),
            ("catalog.productimage", "Product Image"),
            ("auth.user", "User"),
            ("gone.model", "gone.model"),
        ):
            with self.subTest(target_type=target_type):
                self.assertEqual(AuditEvent(target_type=target_type).target_label, label)

    def test_the_trail_cannot_be_written_through_the_api(self):
        recorded = event()
        self.assertEqual(self.client.post(self.URL, {}, format="json").status_code, 405)
        self.assertEqual(self.client.delete(f"{self.URL}{recorded.pk}/").status_code, 405)
        self.assertEqual(
            self.client.patch(f"{self.URL}{recorded.pk}/", {}, format="json").status_code,
            405,
        )

    def test_newest_first_and_filtered(self):
        ravi = make_user(username="ravi", first_name="Ravi")
        created = event(
            actor=self.user,
            actor_name="Asha Rao",
            action=Action.CREATE,
            target_type="orders.order",
            target_id="42",
            target_repr="HG-2026-0042",
        )
        renamed = event(actor=ravi, actor_name="Ravi", target_id="7")
        shipped = event(
            actor=ravi,
            actor_name="Ravi",
            action=Action.ADVANCE_STATUS,
            target_type="orders.order",
            target_id="42",
            target_repr="HG-2026-0042",
        )

        self.assertEqual(self.ids(), [shipped.pk, renamed.pk, created.pk])
        self.assertEqual(self.ids({"actor": ravi.pk}), [shipped.pk, renamed.pk])
        self.assertEqual(self.ids({"action": "update"}), [renamed.pk])
        self.assertEqual(
            self.ids({"target_type": "orders.order", "target_id": "42"}),
            [shipped.pk, created.pk],
        )
        self.assertEqual(self.ids({"search": "ravi"}), [shipped.pk, renamed.pk])
        self.assertEqual(self.ids({"search": "hg-2026"}), [shipped.pk, created.pk])
        self.assertEqual(self.client.get(self.URL, {"action": "erase"}).status_code, 400)

    def test_an_orders_history_is_found_by_its_type_and_id(self):
        order = DisplayOrder.objects.create(name="Holiday", merchant=merchant())
        self.client.post(f"/api/display-orders/{order.pk}/advance-status/")
        event(target_type="display.displayorder", target_id=str(order.pk + 1))

        response = self.client.get(
            self.URL, {"target_type": "display.displayorder", "target_id": order.pk}
        )

        self.assertEqual(
            [(row["action"], row["target_repr"]) for row in response.data["results"]],
            [("advance_status", order.number)],
        )

    def test_dates_are_whole_days_in_the_project_time_zone(self):
        def at(moment):
            with mock.patch(
                "django.utils.timezone.now", return_value=datetime.fromisoformat(moment)
            ):
                return event()

        # Both fall on the 12th in UTC; in Delhi the second is already the 13th.
        late = at("2026-10-12T23:30:00+05:30")
        early = at("2026-10-13T00:30:00+05:30")

        self.assertEqual(self.ids({"created_before": "2026-10-12"}), [late.pk])
        self.assertEqual(self.ids({"created_after": "2026-10-13"}), [early.pk])
        self.assertEqual(
            self.ids({"created_after": "2026-10-12", "created_before": "2026-10-12"}),
            [late.pk],
        )
        self.assertEqual(
            self.ids({"created_after": "2026-10-12", "created_before": "2026-10-13"}),
            [early.pk, late.pk],
        )


@override_settings(STORAGES=local_storage(tempfile.mkdtemp()))
class AdminTests(TestCase):
    def setUp(self):
        root = get_user_model().objects.create_superuser("root", "root@example.com", "x")
        self.client.force_login(root)
        self.event = event(actor=root, actor_name="root")

    def test_the_admin_shows_events_and_cannot_add_change_or_delete_them(self):
        changelist = self.client.get(reverse("admin:audit_auditevent_changelist"))
        self.assertContains(changelist, "Lighting")

        page = self.client.get(reverse("admin:audit_auditevent_change", args=[self.event.pk]))
        self.assertEqual(page.status_code, 200)
        self.assertNotContains(page, 'name="_save"')

        self.assertEqual(
            self.client.get(reverse("admin:audit_auditevent_add")).status_code, 403
        )
        delete = reverse("admin:audit_auditevent_delete", args=[self.event.pk])
        self.assertEqual(self.client.post(delete, {"post": "yes"}).status_code, 403)
        self.assertTrue(AuditEvent.objects.filter(pk=self.event.pk).exists())
