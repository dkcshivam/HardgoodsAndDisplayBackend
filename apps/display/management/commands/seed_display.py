"""
The worked example from ARCHITECTURE.md §10.2: a seasonal store-decor order
and four templates to pack it with.

Wipes the display tables only — Hardgoods data is left alone.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.display.models import (
    DisplayCarton,
    DisplayOrder,
    DisplayOrderLine,
    DisplayProduct,
    PackStep,
    PackTemplate,
    PackTemplateItem,
)
from apps.masters.models import Category, Merchant


def d(value) -> Decimal:
    return Decimal(str(value))


# style_no, description, customs name, hsn, weight kg, L, W, H
PRODUCTS = [
    ("DSP-BOW-12", '12" Velvet Bow', "Decorative Textile Bow", "6307.90",
     0.08, 12, 12, 4),
    ("DSP-ORN-06", "Glass Ornament Set of 6", "Glass Festive Ornaments", "9505.10",
     0.55, 9, 6, 3),
    ("DSP-WRT-24", '24" Pine Wreath', "Artificial Foliage Wreath", "6702.90",
     1.20, 24, 24, 5),
    ("DSP-GRL-72", '72" Cedar Garland', "Artificial Foliage Garland", "6702.90",
     0.90, 14, 10, 8),
]

# code, name, box L/W/H, box kg, packing kg, [(style_no, qty)]
TEMPLATES = [
    ("TPL-001", "30 bows + 5 wreaths", (44, 32, 32), 1.6, 0.5,
     [("DSP-BOW-12", 30), ("DSP-WRT-24", 5)]),
    ("TPL-002", "12 ornament sets + 6 garlands", (30, 20, 20), 0.9, 0.6,
     [("DSP-ORN-06", 12), ("DSP-GRL-72", 6)]),
    ("TPL-003", "6 garlands", (28, 20, 16), 0.8, 0.25,
     [("DSP-GRL-72", 6)]),
    ("TPL-004", "10 wreaths", (42, 30, 30), 1.5, 0.5,
     [("DSP-WRT-24", 10)]),
]

ORDER_LINES = [
    ("DSP-BOW-12", 840, "Cranberry"),
    ("DSP-ORN-06", 96, "Mercury Silver"),
    ("DSP-WRT-24", 140, "Frosted Green"),
    ("DSP-GRL-72", 158, "Natural Cedar"),
]


class Command(BaseCommand):
    help = "Load the Display worked example — products, templates and one order."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Clearing display data...")
        DisplayCarton.objects.all().delete()
        PackStep.objects.all().delete()
        DisplayOrderLine.objects.all().delete()
        DisplayOrder.objects.all().delete()
        PackTemplateItem.objects.all().delete()
        PackTemplate.objects.all().delete()
        DisplayProduct.objects.all().delete()

        category, _ = Category.objects.get_or_create(name="Decor")

        merchant = Merchant.objects.filter(code="TRN").first()
        if merchant is None:
            merchant = Merchant.objects.create(
                code="TRN",
                name="Terrain Home",
                contact_name="Marco Reyes",
                email="marco@terrain.com",
                city="Portland",
                country="US",
            )

        products = {}
        for style_no, description, customs, hsn, weight, length, width, height in PRODUCTS:
            products[style_no] = DisplayProduct.objects.create(
                style_no=style_no,
                description=description,
                category=category,
                customs_description=customs,
                hsn_code=hsn,
                product_weight_kg=d(weight),
                length_in=d(length),
                width_in=d(width),
                height_in=d(height),
            )
        self.stdout.write(f"  {len(products)} products")

        for code, name, box, box_kg, packing_kg, items in TEMPLATES:
            length, width, height = box
            template = PackTemplate.objects.create(
                code=code,
                name=name,
                box_length_in=d(length),
                box_width_in=d(width),
                box_height_in=d(height),
                box_weight_kg=d(box_kg),
                packing_material_weight_kg=d(packing_kg),
                is_library=True,
            )
            PackTemplateItem.objects.bulk_create(
                [
                    PackTemplateItem(
                        template=template, product=products[style_no], quantity=quantity
                    )
                    for style_no, quantity in items
                ]
            )
        self.stdout.write(f"  {len(TEMPLATES)} templates")

        order = DisplayOrder.objects.create(
            name="Terrain Holiday Decor",
            merchant=merchant,
            buyer_name="Marco Reyes",
            ship_country="US",
            ship_line1="900 SE Water Ave",
            ship_city="Portland",
            ship_state="OR",
            ship_postal_code="97214",
        )
        for style_no, quantity, color in ORDER_LINES:
            DisplayOrderLine.objects.create(
                order=order, product=products[style_no], quantity=quantity, color=color
            )

        total = sum(quantity for _, quantity, _ in ORDER_LINES)
        self.stdout.write(f"  1 order ({total} units, no steps yet)")
        self.stdout.write(self.style.SUCCESS("Display demo data loaded."))
