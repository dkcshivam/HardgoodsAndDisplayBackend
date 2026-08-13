from django.db import IntegrityError, transaction
from django.test import TestCase
from rest_framework.test import APITestCase

from .models import Store


class StoreTests(TestCase):
    def test_store_code_is_unique(self):
        # Stores are global, so the number alone identifies an outlet.
        Store.objects.create(code="118", name="Portland")
        with transaction.atomic(), self.assertRaises(IntegrityError):
            Store.objects.create(code="118", name="Duplicate")


class StoreApiTests(APITestCase):
    def payload(self, **overrides):
        data = {
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

    def test_create_returns_the_store(self):
        response = self.client.post("/api/stores/", self.payload(), format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["code"], "118")

    def test_duplicate_code_is_a_400_on_the_code_field(self):
        self.client.post("/api/stores/", self.payload(), format="json")
        response = self.client.post("/api/stores/", self.payload(), format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("code", response.data)

    def test_editing_a_store_keeps_its_own_code(self):
        created = self.client.post("/api/stores/", self.payload(), format="json")
        response = self.client.patch(
            f"/api/stores/{created.data['id']}/",
            {"name": "Portland Pearl"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["name"], "Portland Pearl")

    def test_list_returns_every_store(self):
        self.client.post("/api/stores/", self.payload(), format="json")
        self.client.post(
            "/api/stores/",
            self.payload(code="204", name="Austin"),
            format="json",
        )
        response = self.client.get("/api/stores/")
        self.assertEqual(response.status_code, 200)
        results = response.data["results"]
        self.assertEqual([row["code"] for row in results], ["118", "204"])
