from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APITestCase

from .models import Merchant, Store


def merchant(code, name):
    return Merchant.objects.create(code=code, name=name)


class StoreTests(TestCase):
    def setUp(self):
        self.anthro = merchant("ANT", "Anthropologie")
        self.terrain = merchant("TRN", "Terrain Home")

    def test_store_code_is_unique_within_a_merchant(self):
        Store.objects.create(merchant=self.anthro, code="118", name="Portland")
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Store.objects.create(merchant=self.anthro, code="118", name="Duplicate")

    def test_two_merchants_may_share_a_store_code(self):
        Store.objects.create(merchant=self.anthro, code="118", name="Portland")
        Store.objects.create(merchant=self.terrain, code="118", name="Austin")
        self.assertEqual(Store.objects.filter(code="118").count(), 2)

    def test_a_merchant_with_stores_cannot_be_deleted(self):
        Store.objects.create(merchant=self.anthro, code="118", name="Portland")
        # PROTECT, because losing the merchant would orphan every address a
        # carton is shipped to.
        with self.assertRaises(Exception):
            self.anthro.delete()


class StoreApiTests(APITestCase):
    def setUp(self):
        self.anthro = merchant("ANT", "Anthropologie")
        self.terrain = merchant("TRN", "Terrain Home")

    def payload(self, **overrides):
        data = {
            "merchant": self.anthro.id,
            "code": "118",
            "name": "Portland",
            "ship_line1": "900 SE Water Ave",
            "ship_city": "Portland",
            "ship_state": "OR",
            "ship_postal_code": "97214",
            "ship_country": "US",
        }
        data.update(overrides)
        return data

    def test_create_returns_the_merchant_name(self):
        response = self.client.post("/api/stores/", self.payload(), format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["merchant_name"], "Anthropologie")

    def test_duplicate_code_for_one_merchant_is_a_400(self):
        self.client.post("/api/stores/", self.payload(), format="json")
        response = self.client.post("/api/stores/", self.payload(), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("code", response.data)

    def test_same_code_under_another_merchant_is_allowed(self):
        self.client.post("/api/stores/", self.payload(), format="json")
        response = self.client.post(
            "/api/stores/", self.payload(merchant=self.terrain.id), format="json"
        )
        self.assertEqual(response.status_code, 201)

    def test_editing_a_store_keeps_its_own_code(self):
        created = self.client.post("/api/stores/", self.payload(), format="json")
        response = self.client.patch(
            f"/api/stores/{created.data['id']}/",
            {"name": "Portland Pearl"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "Portland Pearl")

    def test_list_filters_by_merchant(self):
        self.client.post("/api/stores/", self.payload(), format="json")
        self.client.post(
            "/api/stores/",
            self.payload(merchant=self.terrain.id, code="204", name="Austin"),
            format="json",
        )
        response = self.client.get(f"/api/stores/?merchant={self.terrain.id}")
        self.assertEqual(response.status_code, 200)
        results = response.data["results"]
        self.assertEqual([row["code"] for row in results], ["204"])
