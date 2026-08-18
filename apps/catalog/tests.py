import base64
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

from .models import Product, ProductImage, ProductPart

# Smallest thing Pillow will accept as an image.
PIXEL_GIF = base64.b64decode(
    b"R0lGODlhAQABAIAAAP///wAAACH5BAEAAAAALAAAAAABAAEAAAICRAEAOw=="
)


def upload(name="photo.gif"):
    return SimpleUploadedFile(name, PIXEL_GIF, content_type="image/gif")


def part_payload(**overrides):
    """A part complete enough to save. Tests override only what they assert on."""
    return {
        "name": "Part",
        "customs_description": "Wooden furniture part",
        "hsn_code": "9403",
        "box_length_in": "20.00",
        "box_width_in": "14.00",
        "box_height_in": "6.00",
        "product_weight_kg": "4.000",
        "packing_material_weight_kg": "0.200",
        "box_weight_kg": "0.500",
        "sort_order": 0,
        **overrides,
    }


class ProductShapeTests(APITestCase):
    """`is_multi_part` decides how every carton for the SKU is built."""

    def setUp(self):
        self.table = Product.objects.create(
            style_no="TBL-01", description="Table", is_multi_part=True
        )
        self.parts = [
            ProductPart.objects.create(product=self.table, name=name, sort_order=index)
            for index, name in enumerate(("Top", "Legs"))
        ]

    def test_shape_cannot_change_after_creation(self):
        response = self.client.patch(
            f"/api/products/{self.table.pk}/", {"is_multi_part": False}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("is_multi_part", response.data)

    def test_resending_the_same_shape_is_not_a_change(self):
        response = self.client.patch(
            f"/api/products/{self.table.pk}/",
            {"is_multi_part": True, "description": "Oak Table"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)

    def test_editing_parts_keeps_their_rows(self):
        """
        Recreating parts on every save would cascade their photos away, and
        orphan any carton content pointing at them.
        """
        payload = {
            "style_no": "TBL-01",
            "description": "Table",
            "is_multi_part": True,
            "parts": [
                part_payload(id=self.parts[0].pk, name="Table top", sort_order=0),
                part_payload(id=self.parts[1].pk, name="Legs set", sort_order=1),
            ],
        }
        response = self.client.put(
            f"/api/products/{self.table.pk}/", payload, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [part.pk for part in self.parts],
            list(self.table.parts.values_list("id", flat=True)),
        )
        self.parts[0].refresh_from_db()
        self.assertEqual(self.parts[0].name, "Table top")

    def test_a_part_dropped_from_the_payload_is_deleted(self):
        payload = {
            "style_no": "TBL-01",
            "description": "Table",
            "is_multi_part": True,
            "parts": [
                part_payload(id=self.parts[0].pk, name="Top", sort_order=0),
                part_payload(name="Fixings", sort_order=1),
            ],
        }
        response = self.client.put(
            f"/api/products/{self.table.pk}/", payload, format="json"
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.table.parts.count(), 2)
        self.assertFalse(ProductPart.objects.filter(pk=self.parts[1].pk).exists())


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class ProductPhotoTests(APITestCase):
    def setUp(self):
        self.chair = Product.objects.create(style_no="CHR-01", description="Chair")
        self.table = Product.objects.create(
            style_no="TBL-01", description="Table", is_multi_part=True
        )
        self.part = ProductPart.objects.create(product=self.table, name="Top")

    def post(self, **data):
        return self.client.post("/api/product-images/", data, format="multipart")

    def test_a_photo_belongs_to_exactly_one_owner(self):
        self.assertEqual(self.post(image=upload()).status_code, 400)
        self.assertEqual(
            self.post(image=upload(), product=self.chair.pk, part=self.part.pk).status_code,
            400,
        )

    def test_first_photo_of_an_owner_becomes_its_main_one(self):
        first = self.post(image=upload("a.gif"), product=self.chair.pk)
        second = self.post(image=upload("b.gif"), product=self.chair.pk)

        self.assertEqual(first.status_code, 201)
        self.assertTrue(first.data["is_main"])
        self.assertFalse(second.data["is_main"])

    def test_setting_a_new_main_photo_demotes_the_old_one(self):
        first = self.post(image=upload("a.gif"), product=self.chair.pk)
        second = self.post(image=upload("b.gif"), product=self.chair.pk)

        self.client.patch(
            f"/api/product-images/{second.data['id']}/", {"is_main": True}, format="json"
        )

        self.assertFalse(ProductImage.objects.get(pk=first.data["id"]).is_main)
        self.assertTrue(ProductImage.objects.get(pk=second.data["id"]).is_main)

    def test_part_photos_survive_a_product_save(self):
        self.post(image=upload(), part=self.part.pk)

        response = self.client.patch(
            f"/api/products/{self.table.pk}/",
            {
                "parts": [
                    {"id": self.part.pk, "name": "Table top", "sort_order": 0},
                    {"name": "Legs set", "sort_order": 1},
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.part.images.count(), 1)

    def test_the_product_list_carries_the_main_photo(self):
        self.post(image=upload(), product=self.chair.pk)

        response = self.client.get("/api/products/", {"search": "CHR-01"})
        row = response.data["results"][0]

        self.assertIn("/media/products/", row["main_image"])
