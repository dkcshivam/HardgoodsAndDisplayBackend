"""
The Display packing list, in store order.

A carton ships to exactly one store, so the sheet is blocked by store: each
one opens with its name and address, carries its own rows, and closes with
its own subtotal. That is the shape the warehouse reads it in — they are
picking a pallet per store, not per order — and it is the shape a customs
broker checks it in.

The grouping and sheet furniture are shared with Hardgoods; only the blocking
is particular to Display.
"""

from collections import Counter
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook

from apps.common import invoice_sheet as invoice_kit
from apps.common import packing_sheet as sheet_kit

from . import services
from .models import DisplayOrder, DisplayProduct


# The carton count goes: "BOX-001 – BOX-012" already says twelve. The store
# is not a column either — every row already sits under the banner naming the
# store it ships to, and repeating it on all 563 rows only makes the sheet
# wider than a page.
_DROPPED = "Cartons"

LAYOUT = sheet_kit.Layout(
    columns=[
        column for column in sheet_kit.COLUMNS if column[0] != _DROPPED
    ],
    totalled=sheet_kit.TOTALLED - {_DROPPED},
)


#: Our own letterhead — constant, so it lives here rather than in a settings
#: table nobody would ever edit.
EXPORTER = [
    "DKC EXPORTS PVT LTD",
    "A-4 Shiv Marg, Green Avenue, Church Road",
    "Vasant Kunj, New Delhi 110070, INDIA",
    "Tel +91 11 26124358",
]


def invoice_filename(order: DisplayOrder) -> str:
    return f"invoice-{order.number}.xlsx"


def packing_list_filename(order: DisplayOrder) -> str:
    return f"packing-list-{order.number}.xlsx"


_KEPT = [
    index
    for index, (label, _, _) in enumerate(sheet_kit.COLUMNS)
    if label != _DROPPED
]


def _for_sheet(values: list) -> list:
    """A canonical row from the shared kit, minus the columns we do not print."""
    return [values[index] for index in _KEPT]


def packing_document(order: DisplayOrder) -> sheet_kit.Document:
    cartons = list(
        order.cartons.select_related("store").prefetch_related(
            "contents__product", "contents__part"
        )
    )
    by_store: dict[int, list] = {}
    for carton in cartons:
        by_store.setdefault(carton.store_id, []).append(carton)

    order_totals = sheet_kit.Totals()
    blocks = []
    # The sheet numbers its own boxes rather than printing `carton_no`: the
    # stored numbers run in step order, which interleaves the stores this
    # sheet is blocked by. See `number_groups` and §10.6.
    next_box = 1

    for store in _stores_in_order(order, by_store):
        cartons_here = by_store.get(store.id, [])
        if not cartons_here:
            continue

        store_totals = sheet_kit.Totals()
        rows = []
        groups = sheet_kit.group_cartons(cartons_here)
        next_box = sheet_kit.number_groups(groups, next_box)
        for group in groups:
            store_totals.add(group)
            for position, values in enumerate(group.rows()):
                rows.append((_for_sheet(values), position == 0))

        blocks.append(
            sheet_kit.Block(
                rows=rows,
                banner=_store_label(store),
                subtotal=store_totals,
                subtotal_label=(
                    f"{store.name} subtotal · all {_boxes(store_totals.cartons)}"
                ),
            )
        )
        order_totals.merge(store_totals)

    stores = {line.store_id for line in order.lines.all()}
    return sheet_kit.Document(
        title="PACKING LIST",
        facts=[
            ("Order", order.number),
            ("Name", order.name),
            ("Merchant", order.merchant.name),
            ("Buyer", order.buyer_name),
            ("Stores", f"{len(stores)}"),
            ("Status", order.get_status_display()),
        ],
        blocks=blocks,
        total=order_totals,
        total_label=f"ORDER TOTAL · all {_boxes(order_totals.cartons)}",
        layout=LAYOUT,
    )


def build_packing_list(order: DisplayOrder) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = order.number

    sheet_kit.write_document(sheet, packing_document(order))

    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


def _boxes(count: int) -> str:
    return f"{count} box{'es' if count != 1 else ''}"


def _stores_in_order(order: DisplayOrder, by_store: dict) -> list:
    """Stores that actually have cartons, in the order the lines name them."""
    seen, stores = set(), []
    for line in order.lines.select_related("store"):
        if line.store_id in seen or line.store_id not in by_store:
            continue
        seen.add(line.store_id)
        stores.append(line.store)
    return stores


def _store_label(store) -> str:
    address = ", ".join(
        part
        for part in (
            store.ship_line1,
            store.ship_line2,
            store.ship_city,
            store.ship_state,
            store.ship_postal_code,
            store.ship_country,
        )
        if part
    )
    head = f"STORE {store.name}"
    return f"{head} — {address}" if address else head


def invoice_document(order: DisplayOrder) -> invoice_kit.Document:
    """
    One row per style across the whole order, priced from the order's rates.

    Billed on what is **packed**, not what was ordered, and counted the way
    `reconcile` counts it — a multi-part style is a unit only once every
    piece of it has a box. That keeps this document and the packing list
    agreeing on a single number, which is the pair a broker checks first.
    """
    rates = {rate.product_id: rate.rate_usd for rate in order.rates.all()}
    packed = Counter()
    for line in services.reconcile(order):
        packed[line.product] += line.packed

    invoice = invoice_kit.Invoice()
    products = {
        product.id: product
        for product in DisplayProduct.objects.filter(
            id__in=packed
        ).prefetch_related("parts")
    }

    for product_id, quantity in packed.items():
        if quantity == 0:
            continue
        product = products[product_id]
        invoice.add(
            product_id,
            style_no=product.style_no,
            hts_code=_hsn(product),
            description=_customs(product),
            quantity=quantity,
            net_weight_kg=_unit_weight(product) * quantity,
            rate=rates.get(product_id),
        )

    stores = len({line.store_id for line in order.lines.all()})
    return invoice_kit.Document(
        exporter=EXPORTER,
        consignee=[order.buyer_name or order.merchant.name],
        ship_to=[f"{stores} stores"],
        invoice=invoice,
    )


def build_invoice(order: DisplayOrder) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Invoice"

    invoice_kit.write_document(sheet, invoice_document(order))

    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


def _hsn(product) -> str:
    """A part's code where the product has none — they may differ per part."""
    if product.hsn_code:
        return product.hsn_code
    return next((part.hsn_code for part in product.parts.all() if part.hsn_code), "")


def _customs(product) -> str:
    return (
        product.customs_description
        or product.style_name
        or product.description
        or product.style_no
    )


def _unit_weight(product) -> Decimal:
    """One saleable unit: the item, or every part of it together."""
    if product.is_multi_part:
        return sum(
            (part.product_weight_kg or Decimal("0") for part in product.parts.all()),
            start=Decimal("0"),
        )
    return product.product_weight_kg or Decimal("0")
