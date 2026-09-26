import shutil
import tempfile
from io import StringIO
from pathlib import Path

from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from apps.common.testing import local_storage

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


class CopyMediaToStorageTests(TestCase):
    """The one-time move of images off disk, with a folder standing in for S3."""

    def setUp(self):
        self.source = Path(tempfile.mkdtemp())
        self.target = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.source)
        self.addCleanup(shutil.rmtree, self.target)
        photo = self.source / "display" / "products" / "57" / "pendant.png"
        photo.parent.mkdir(parents=True)
        photo.write_bytes(b"png")

    def copy(self, into):
        out = StringIO()
        with override_settings(STORAGES=local_storage(into)):
            call_command("copy_media_to_storage", source=str(self.source), stdout=out)
        return out.getvalue()

    def test_every_file_keeps_the_path_the_database_knows_it_by(self):
        self.copy(self.target)
        copied = self.target / "display" / "products" / "57" / "pendant.png"
        self.assertEqual(copied.read_bytes(), b"png")

    def test_a_second_run_copies_nothing_twice(self):
        self.copy(self.target)
        self.assertIn("Copied 0, already there 1.", self.copy(self.target))

    def test_it_refuses_to_copy_a_folder_onto_itself(self):
        with self.assertRaisesMessage(CommandError, "AWS_STORAGE_BUCKET_NAME"):
            self.copy(self.source)
