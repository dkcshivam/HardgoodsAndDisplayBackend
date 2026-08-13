"""
A clean product catalogue for manual testing — 15 Display products, some
single-part and some multi-part, and nothing else. No templates, no orders:
build those yourself through the app.

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
    DisplayProductPart,
    PackStep,
    PackTemplate,
    PackTemplateItem,
)
from apps.masters.models import Category, Store


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
    ("DSP-LAN-10", '10" Metal Lantern', "Decorative Metal Lantern", "8306.29",
     0.75, 10, 10, 14),
    ("DSP-CDH-08", '8" Ceramic Candle Holder', "Ceramic Candle Holder", "6913.90",
     0.40, 8, 8, 8),
    ("DSP-PLN-14", '14" Terracotta Planter', "Ceramic Planter", "6914.90",
     1.80, 14, 14, 12),
    ("DSP-RUN-90", '90" Linen Table Runner', "Textile Table Runner", "6304.93",
     0.30, 20, 6, 2),
    ("DSP-STK-18", '18" Knit Stocking', "Knitted Textile Stocking", "6307.90",
     0.20, 18, 8, 2),
    ("DSP-SNG-05", '5" Glass Snow Globe', "Glass Snow Globe", "9505.10",
     0.65, 5, 5, 6),
]

# Products whose parts are packed apart — too big, too different in shape,
# or just don't fit in one box together.
# style_no, description, [(part name, customs, hsn, weight kg, L, W, H)]
PART_PRODUCTS = [
    ("DSP-TRE-60", '60" Display Tree', [
        ("Branch panels", "Artificial Foliage Panels", "6702.90", 3.40, 30, 22, 6),
        ("Trunk and stand", "Metal Display Stand", "7326.90", 4.80, 46, 8, 8),
    ]),
    ("DSP-LDR-72", '72" Ladder Shelf', [
        ("Side rails", "Wooden Ladder Rails", "4421.99", 3.20, 72, 4, 2),
        ("Shelf boards", "Wooden Shelf Boards", "4421.99", 2.10, 24, 10, 1),
    ]),
    ("DSP-ARC-84", '84" Garden Arch', [
        ("Left post", "Metal Arch Post", "7326.90", 4.50, 84, 4, 4),
        ("Right post", "Metal Arch Post", "7326.90", 4.50, 84, 4, 4),
        ("Top arch", "Metal Arch Top", "7326.90", 3.80, 40, 40, 4),
    ]),
    ("DSP-SCR-60", '60" Room Divider Screen', [
        ("Panel A", "Wooden Screen Panel", "4421.99", 5.00, 60, 20, 2),
        ("Panel B", "Wooden Screen Panel", "4421.99", 5.00, 60, 20, 2),
        ("Panel C", "Wooden Screen Panel", "4421.99", 5.00, 60, 20, 2),
    ]),
    ("DSP-TBL-48", '48" Display Table', [
        ("Tabletop", "Wooden Table Top", "4421.99", 6.00, 48, 24, 3),
        ("Legs and base", "Metal Table Base", "9403.90", 5.50, 24, 24, 20),
    ]),
]


# The outlets an order gets split across.
# code, name, city, state, postcode
STORES = [
    ("118", "Portland Pearl", "900 SE Water Ave", "Portland", "OR", "97214"),
    ("204", "Austin Domain", "11800 Domain Blvd", "Austin", "TX", "78758"),
    ("331", "Brooklyn Williamsburg", "62 N 6th St", "Brooklyn", "NY", "11249"),
    ("407", "Chicago Lincoln Park", "1500 N Halsted St", "Chicago", "IL", "60642"),
    ("512", "Seattle University Village", "2623 NE University Village St",
     "Seattle", "WA", "98105"),
    ("628", "Denver Cherry Creek", "2800 E 1st Ave", "Denver", "CO", "80206"),
]


class Command(BaseCommand):
    help = "Load a clean Display product catalogue — no templates, no orders."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Clearing display data...")
        DisplayCarton.objects.all().delete()
        PackStep.objects.all().delete()
        DisplayOrderLine.objects.all().delete()
        DisplayOrder.objects.all().delete()
        PackTemplateItem.objects.all().delete()
        PackTemplate.objects.all().delete()
        DisplayProductPart.objects.all().delete()
        DisplayProduct.objects.all().delete()

        category, _ = Category.objects.get_or_create(name="Decor")

        for code, name, line1, city, state, postcode in STORES:
            Store.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "ship_line1": line1,
                    "ship_city": city,
                    "ship_state": state,
                    "ship_postal_code": postcode,
                    "ship_country": "US",
                },
            )

        for style_no, description, customs, hsn, weight, length, width, height in PRODUCTS:
            DisplayProduct.objects.create(
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

        for style_no, description, part_specs in PART_PRODUCTS:
            product = DisplayProduct.objects.create(
                style_no=style_no,
                description=description,
                category=category,
                is_multi_part=True,
            )
            for order_index, spec in enumerate(part_specs):
                name, customs, hsn, weight, length, width, height = spec
                DisplayProductPart.objects.create(
                    product=product,
                    name=name,
                    customs_description=customs,
                    hsn_code=hsn,
                    product_weight_kg=d(weight),
                    length_in=d(length),
                    width_in=d(width),
                    height_in=d(height),
                    sort_order=order_index,
                )

        total_products = len(PRODUCTS) + len(PART_PRODUCTS)
        self.stdout.write(
            f"  {total_products} products ({len(PART_PRODUCTS)} multi-part, "
            f"{len(PRODUCTS)} single-part)"
        )
        self.stdout.write(f"  {len(STORES)} stores")
        self.stdout.write(self.style.SUCCESS(
            "Display catalogue loaded — no templates or orders. Build those yourself."
        ))
