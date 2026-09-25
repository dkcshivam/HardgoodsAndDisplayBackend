"""
The Display packing list, in store order.

A carton ships to exactly one store, so the sheet runs store by store in the
order's sequence, naming the store on the first row of its run. The layout
follows the list the shipping desk made by hand (`PL 001.xlsx`): a serial
number per row, the box count, the store, then each box's sides in inches and
in centimetres.

The grouping and sheet furniture are shared with Hardgoods; the columns and
the store run are particular to Display.
"""

from collections import Counter
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook

from apps.common import export_header
from apps.common import invoice_sheet as invoice_kit
from apps.common import packing_sheet as sheet_kit

from . import services
from .models import DisplayOrder, DisplayProduct


LAYOUT = sheet_kit.Layout(
    columns=[
        # Wide enough for the order facts above the table, which share it.
        ("SNO", 10, "0"),
        # A number format so a lone box and a `10 – 14` run align alike.
        ("Carton Nos", 20, "0"),
        ("Total No of Boxes", 9, "0"),
        ("Store No", 12, None),
        ("Style No", 18, None),
        ("Customs Description", 34, None),
        ("Qty / Box", 9, "0"),
        ("Units", 8, None),
        ("NNW (kg)", 11, "0.000"),
        ("N.W. (kg)", 11, "0.000"),
        ("G.W. (kg)", 11, "0.000"),
        ("L (in)", 9, "0.00"),
        ("W (in)", 9, "0.00"),
        ("H (in)", 9, "0.00"),
        ("L (cm)", 9, "0.00"),
        ("W (cm)", 9, "0.00"),
        ("H (cm)", 9, "0.00"),
        ("CBM", 10, "0.0000"),
    ],
    totalled={
        "Total No of Boxes",
        "Qty / Box",
        "NNW (kg)",
        "N.W. (kg)",
        "G.W. (kg)",
        "CBM",
    },
    header=export_header.Grid(left=5, split=2, middle=11, beside=8, labels=13, last=18),
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


def _for_sheet(serial: int, store_no, sample, values: list, opens: bool) -> list:
    """
    A canonical row from the shared kit, laid out in Display's columns. The
    inches are the box's own; the centimetres are the kit's, converted from
    them, and the CBM is worked from those centimetres.
    """
    label, count, *item, length_cm, width_cm, height_cm, cbm = values
    inches = (
        [sample.length_in, sample.width_in, sample.height_in] if opens else [None] * 3
    )
    return [
        serial,
        label,
        count,
        store_no,
        *item,
        *inches,
        length_cm,
        width_cm,
        height_cm,
        cbm,
    ]


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
    serial = 0

    for store in _stores_in_order(order, by_store):
        cartons_here = by_store.get(store.id, [])
        if not cartons_here:
            continue

        rows = []
        groups = sheet_kit.group_cartons(cartons_here)
        next_box = sheet_kit.number_groups(groups, next_box)
        for group in groups:
            order_totals.add(group)
            for position, values in enumerate(group.rows()):
                serial += 1
                opens = position == 0
                # Named once, where its run starts, as the hand-made list does.
                store_no = _store_no(store) if not rows else None
                rows.append(
                    (
                        _for_sheet(serial, store_no, group.cartons[0], values, opens),
                        opens,
                    )
                )

        blocks.append(sheet_kit.Block(rows=rows))

    stores = {line.store_id for line in order.lines.all()}
    return sheet_kit.Document(
        title="PACKING LIST",
        order_title=order.name,
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
        export_details=order.export_details or {},
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


def _store_no(store):
    """A number where the name is one, so Excel does not flag it as text."""
    return int(store.name) if store.name.isdigit() else store.name


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
            hts_code=_hts(product),
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


def _hts(product) -> str:
    """
    The US tariff code, never the HSN: the buyer's customs clear on HTS. A
    part's code where the product has none — they may differ per part.
    """
    if product.hts_code:
        return product.hts_code
    return next((part.hts_code for part in product.parts.all() if part.hts_code), "")


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
