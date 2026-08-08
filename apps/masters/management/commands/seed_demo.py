"""
Sample data from the approved prototype. Safe to re-run — it wipes the
tables first, so never point it at real data.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import connection, transaction

from apps.catalog.models import Product, ProductPart
from apps.masters.models import Category, Merchant
from apps.orders.models import Carton, Order, OrderLine
from apps.orders.services import apply_packing_plan, build_packing_plan


def d(value) -> Decimal:
    return Decimal(str(value))


CATEGORIES = ["Table", "Chair", "Storage", "Stool", "Decor", "Lighting"]

MERCHANTS = [
    ("UO", "Urban Outfitters Inc", "Dana Whitfield", "dana@urbn.com",
     "+1 215 555 0142", "Philadelphia", "US"),
    ("TRN", "Terrain Home", "Marco Reyes", "marco@terrain.com",
     "+1 503 555 0088", "Portland", "US"),
    ("WE", "West Elm Group", "Priya Anand", "priya@westelm.com",
     "+1 718 555 0203", "Brooklyn", "US"),
    ("ANTH", "Anthropologie", "Leon Garcia", "leon@anthro.com",
     "+1 215 555 0777", "Philadelphia", "US"),
]

# style_no, description, category, status, pack_per_box,
# assembled L/W/H/kg, single-box spec or parts
PRODUCTS = [
    {
        "style_no": "DKC-TBL-OAK-01",
        "description": "Oak Dining Table",
        "category": "Table",
        "assembled": (72, 40, 30, 34),
        "customs": ("Wooden Dining Table", "9403.30"),
        "parts": [
            {
                "name": "Table top",
                "description": "Oak table top, foam-wrapped",
                "customs": ("Wooden Table Top", "9403.30"),
                "size": (72, 40, 4),
                "weight": 20,
                "box_size": (76, 44, 8),
            },
            {
                "name": "Legs set",
                "description": "4 legs + fixings bag",
                "customs": ("Wooden Furniture Legs", "9403.90"),
                "size": (30, 8, 8),
                "weight": 14,
                "box_size": (34, 12, 12),
            },
        ],
    },
    {
        "style_no": "DKC-CHR-OAK-02",
        "description": "Oak Dining Chair",
        "category": "Chair",
        "assembled": (20, 22, 34, 6),
        "customs": ("Wooden Dining Chair", "9401.61"),
        "pack_per_box": 2,
        "single": {"weight": 6, "box_size": (40, 30, 24)},
    },
    {
        "style_no": "DKC-SDB-WAL-07",
        "description": "Walnut Sideboard",
        "category": "Storage",
        "assembled": (64, 18, 32, 46),
        "customs": ("Wooden Sideboard", "9403.50"),
        "parts": [
            {
                "name": "Body",
                "description": "Sideboard carcass",
                "customs": ("Wooden Cabinet Carcass", "9403.50"),
                "size": (64, 18, 26),
                "weight": 38,
                "box_size": (66, 20, 28),
            },
            {
                "name": "Doors & shelves",
                "description": "2 doors, 2 shelves, hardware",
                "customs": ("Wooden Cabinet Doors and Shelves", "9403.90"),
                "size": (40, 18, 6),
                "weight": 8,
                "box_size": (44, 20, 8),
            },
        ],
    },
    {
        "style_no": "DKC-MIR-BRS-08",
        "description": "Brass Floor Mirror",
        "category": "Decor",
        "assembled": (30, 2, 70, 12),
        "customs": ("Framed Glass Mirror", "7009.92"),
        "single": {"weight": 12, "box_size": (34, 6, 74)},
    },
    {
        "style_no": "DKC-STL-OAK-05",
        "description": "Oak Bar Stool",
        "category": "Stool",
        "assembled": (16, 16, 30, 5),
        "customs": ("Wooden Bar Stool", "9401.69"),
        "pack_per_box": 2,
        "single": {"weight": 5, "box_size": (24, 18, 14)},
    },
    {
        "style_no": "DKC-DRS-OAK-06",
        "description": "6-Drawer Dresser",
        "category": "Storage",
        "assembled": (60, 20, 34, 52),
        "customs": ("Wooden Chest of Drawers", "9403.50"),
        "single": {"weight": 52, "box_size": (60, 40, 36)},
    },
    {
        "style_no": "DKC-BKC-WAL-03",
        "description": "Walnut Bookcase",
        "category": "Storage",
        "assembled": (36, 12, 72, 40),
        "customs": ("Wooden Bookcase", "9403.50"),
        "parts": [
            {
                "name": "Frame",
                "description": "Bookcase frame",
                "customs": ("Wooden Bookcase Frame", "9403.50"),
                "size": (36, 12, 72),
                "weight": 30,
                "box_size": (40, 14, 74),
            },
            {
                "name": "Shelves",
                "description": "5 shelves + pins",
                "customs": ("Wooden Shelving Boards", "9403.90"),
                "size": (34, 11, 4),
                "weight": 10,
                "box_size": (38, 13, 6),
            },
        ],
    },
    {
        "style_no": "DKC-CFT-MRB-04",
        "description": "Marble Coffee Table",
        "category": "Table",
        "status": "inactive",
        "assembled": (48, 24, 18, 28),
        "customs": ("Marble Top Coffee Table", "9403.30"),
        "parts": [
            {
                "name": "Marble top",
                "description": "Marble slab, crated",
                "customs": ("Worked Marble Slab", "6802.91"),
                "size": (48, 24, 2),
                "weight": 20,
                "box_size": (52, 28, 6),
            },
            {
                "name": "Metal base",
                "description": "Powder-coated base",
                "customs": ("Steel Furniture Base", "9403.20"),
                "size": (24, 24, 16),
                "weight": 8,
                "box_size": (28, 28, 18),
            },
        ],
    },
]

UO_ADDRESS = {
    "ship_country": "US",
    "ship_line1": "5000 South Broad St",
    "ship_city": "Philadelphia",
    "ship_state": "PA",
    "ship_postal_code": "19112",
}

# Order lines are (style_no, quantity, colour) — the same SKU ships in
# whatever finish that order asked for.
ORDERS = [
    {
        "name": "UO Fall Dining Refresh",
        "merchant": "UO",
        "buyer": "Dana Whitfield",
        "address": UO_ADDRESS,
        "status": "draft",
        "lines": [
            ("DKC-TBL-OAK-01", 3, "Natural Oak"),
            ("DKC-CHR-OAK-02", 6, "Natural Oak"),
            ("DKC-MIR-BRS-08", 4, "Antique Brass"),
        ],
    },
    {
        "name": "UO Spring Seating",
        "merchant": "UO",
        "buyer": "Dana Whitfield",
        "address": UO_ADDRESS,
        "status": "packing",
        "lines": [
            ("DKC-CHR-OAK-02", 20, "Charcoal Wash"),
            ("DKC-STL-OAK-05", 12, "Natural Oak"),
        ],
    },
    {
        "name": "Terrain Patio Set",
        "merchant": "TRN",
        "buyer": "Marco Reyes",
        "address": {
            "ship_country": "US",
            "ship_line1": "900 SE Water Ave",
            "ship_city": "Portland",
            "ship_state": "OR",
            "ship_postal_code": "97214",
        },
        "status": "packed",
        "lines": [
            ("DKC-TBL-OAK-01", 2, "Whitewash"),
            ("DKC-CHR-OAK-02", 8, "Whitewash"),
        ],
    },
    {
        "name": "West Elm Bookcases",
        "merchant": "WE",
        "buyer": "Priya Anand",
        "address": {
            "ship_country": "US",
            "ship_line1": "55 Water St",
            "ship_city": "Brooklyn",
            "ship_state": "NY",
            "ship_postal_code": "11201",
        },
        "status": "shipped",
        "lines": [("DKC-BKC-WAL-03", 15, "Dark Walnut")],
    },
    {
        "name": "UO Bar Refresh",
        "merchant": "UO",
        "buyer": "Dana Whitfield",
        "address": UO_ADDRESS,
        "status": "draft",
        "lines": [
            ("DKC-STL-OAK-05", 24, "Natural Oak"),
            ("DKC-SDB-WAL-07", 4, "Dark Walnut"),
        ],
    },
]


def packaging_weights(item_weight_kg: float) -> tuple[Decimal, Decimal]:
    """
    Invented — the prototype only recorded item weight. Kept proportional so
    gross always exceeds net and nothing trips a blocker.
    """
    box = max(Decimal("0.400"), (d(item_weight_kg) * d("0.09")).quantize(d("0.001")))
    packing = max(Decimal("0.100"), (d(item_weight_kg) * d("0.04")).quantize(d("0.001")))
    return box, packing


def reset_sequences():
    """Restart ids at 1 so a reseed always produces the same links."""
    models = [Carton, Order, OrderLine, ProductPart, Product, Category, Merchant]
    with connection.cursor() as cursor:
        for model in models:
            table = model._meta.db_table
            cursor.execute(
                f"ALTER SEQUENCE {table}_id_seq RESTART WITH 1"  # noqa: S608 - table names are ours
            )


class Command(BaseCommand):
    help = "Load sample hardgoods data from the approved prototype."

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("Clearing existing demo data...")
        Carton.objects.all().delete()
        OrderLine.objects.all().delete()
        Order.objects.all().delete()
        ProductPart.objects.all().delete()
        Product.objects.all().delete()
        Category.objects.all().delete()
        Merchant.objects.all().delete()
        reset_sequences()

        categories = {
            name: Category.objects.create(name=name) for name in CATEGORIES
        }
        self.stdout.write(f"  {len(categories)} categories")

        merchants = {
            code: Merchant.objects.create(
                code=code,
                name=name,
                contact_name=contact,
                email=email,
                phone=phone,
                city=city,
                country=country,
            )
            for code, name, contact, email, phone, city, country in MERCHANTS
        }
        self.stdout.write(f"  {len(merchants)} merchants")

        products = {}
        part_total = 0

        for spec in PRODUCTS:
            length, width, height, weight = spec["assembled"]
            customs_name, hsn = spec["customs"]
            is_multi_part = "parts" in spec

            product = Product(
                style_no=spec["style_no"],
                description=spec["description"],
                category=categories[spec["category"]],
                customs_description="" if is_multi_part else customs_name,
                hsn_code="" if is_multi_part else hsn,
                is_multi_part=is_multi_part,
                status=spec.get("status", "active"),
                assembled_length_in=d(length),
                assembled_width_in=d(width),
                assembled_height_in=d(height),
                assembled_weight_kg=d(weight),
                pack_per_box=spec.get("pack_per_box", 1),
            )

            if not is_multi_part:
                single = spec["single"]
                box_l, box_w, box_h = single["box_size"]
                box_kg, packing_kg = packaging_weights(single["weight"])
                product.box_length_in = d(box_l)
                product.box_width_in = d(box_w)
                product.box_height_in = d(box_h)
                product.product_weight_kg = d(single["weight"])
                product.box_weight_kg = box_kg
                product.packing_material_weight_kg = packing_kg

            product.save()
            products[product.style_no] = product

            for order_index, part_spec in enumerate(spec.get("parts", [])):
                part_l, part_w, part_h = part_spec["size"]
                box_l, box_w, box_h = part_spec["box_size"]
                box_kg, packing_kg = packaging_weights(part_spec["weight"])
                part_customs, part_hsn = part_spec["customs"]

                ProductPart.objects.create(
                    product=product,
                    name=part_spec["name"],
                    description=part_spec["description"],
                    customs_description=part_customs,
                    hsn_code=part_hsn,
                    length_in=d(part_l),
                    width_in=d(part_w),
                    height_in=d(part_h),
                    box_length_in=d(box_l),
                    box_width_in=d(box_w),
                    box_height_in=d(box_h),
                    product_weight_kg=d(part_spec["weight"]),
                    box_weight_kg=box_kg,
                    packing_material_weight_kg=packing_kg,
                    sort_order=order_index,
                )
                part_total += 1

        self.stdout.write(f"  {len(products)} products ({part_total} parts)")

        packed_orders = 0

        for spec in ORDERS:
            order = Order.objects.create(
                name=spec["name"],
                merchant=merchants[spec["merchant"]],
                buyer_name=spec["buyer"],
                status=spec["status"],
                **spec["address"],
            )
            for style_no, quantity, color in spec["lines"]:
                OrderLine.objects.create(
                    order=order,
                    product=products[style_no],
                    quantity=quantity,
                    color=color,
                )

            # Drafts are left empty so the packing screen's blank state shows.
            if spec["status"] != "draft":
                apply_packing_plan(order, build_packing_plan(order))
                packed_orders += 1

        self.stdout.write(f"  {len(ORDERS)} orders ({packed_orders} with carton plans)")
        self.stdout.write(self.style.SUCCESS("Demo data loaded."))
