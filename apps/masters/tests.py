from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APITestCase

from .models import Store


class StoreTests(TestCase):
    def test_store_name_is_unique(self):
        # Stores are global and carry no separate number, so the name alone
        # identifies an outlet.
        Store.objects.create(name="118 Portland Pearl")
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Store.objects.create(name="118 Portland Pearl")


class StoreApiTests(APITestCase):
    def payload(self, **overrides):
        data = {
            "name": "118 Portland Pearl",
            "ship_line1": "900 SE Water Ave",
            "ship_city": "Portland",
            "ship_state": "OR",
            "ship_postal_code": "97214",
            "ship_country": "US",
        }
        data.update(overrides)
        return data

    def test_create_returns_the_store(self):
        response = self.client.post("/api/stores/", self.payload(), format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["name"], "118 Portland Pearl")

    def test_duplicate_name_is_a_400_on_the_name_field(self):
        self.client.post("/api/stores/", self.payload(), format="json")
        response = self.client.post("/api/stores/", self.payload(), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("name", response.data)

    def test_editing_a_store_keeps_its_own_name(self):
        created = self.client.post("/api/stores/", self.payload(), format="json")
        response = self.client.patch(
            f"/api/stores/{created.data['id']}/",
            {"ship_city": "Portland OR"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "118 Portland Pearl")

    def test_list_returns_every_store(self):
        self.client.post("/api/stores/", self.payload(), format="json")
        self.client.post(
            "/api/stores/", self.payload(name="204 Austin Domain"), format="json"
        )
        response = self.client.get("/api/stores/")
        self.assertEqual(response.status_code, 200)
        results = response.data["results"]
        self.assertEqual(
            [row["name"] for row in results],
            ["118 Portland Pearl", "204 Austin Domain"],
        )
