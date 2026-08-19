"""
The packing list as the shipping desk sends it: one row per distinct thing
packed, not per carton. Twelve identical cartons of one chair collapse to a
single row carrying their carton range and count, so the sheet is as long as
the order has different items rather than as long as it has boxes.

The grouping and the sheet furniture live in `apps/common/packing_sheet.py`,
shared with Display.
"""

from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font

from apps.common import invoice_sheet as invoice_kit
from apps.common import packing_sheet as sheet_kit

from . import services
from .models import Order


#: Our own letterhead — constant, so it lives here rather than in a settings
#: table nobody would ever edit.
EXPORTER = [
    "DKC EXPORTS PVT LTD",
    "A-4 Shiv Marg, Green Avenue, Church Road",
    "Vasant Kunj, New Delhi 110070, INDIA",
    "Tel +91 11 26124358",
]


def invoice_filename(order: Order) -> str:
    return f"invoice-{order.number}.xlsx"


def packing_list_filename(order: Order) -> str:
    return f"packing-list-{order.number}.xlsx"


def build_packing_list(order: Order) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = order.number

    sheet_kit.set_widths(sheet)

    row = _write_heading(sheet, order)
    header_row = row + 1
    sheet_kit.write_column_headers(sheet, header_row)

    row = header_row + 1
    first_data_row = row

    cartons = list(
        order.cartons.prefetch_related("contents__product", "contents__part")
    )

    totals = sheet_kit.Totals()
    for group in sheet_kit.group_cartons(cartons):
        totals.add(group)
        for position, values in enumerate(group.rows()):
            sheet_kit.write_row(sheet, row, values, opens=position == 0)
            row += 1

    count = totals.cartons
    sheet_kit.write_totals(
        sheet,
        row,
        totals,
        f"TOTAL · all {count} box{'es' if count != 1 else ''}",
    )
    sheet.freeze_panes = sheet.cell(row=first_data_row, column=1)

    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


def _write_heading(sheet, order: Order) -> int:
    title = sheet.cell(row=1, column=1, value="PACKING LIST")
    title.font = Font(bold=True, size=15)

    return sheet_kit.write_facts(
        sheet,
        2,
        [
            ("Order", order.number),
            ("Name", order.name),
            ("Merchant", order.merchant.name),
            ("Buyer", order.buyer_name),
            ("Ship to", _address(order)),
            ("Status", order.get_status_display()),
        ],
    )


def _address(order: Order) -> str:
    parts = [
        order.ship_line1,
        order.ship_line2,
        order.ship_city,
        order.ship_state,
        order.ship_postal_code,
        order.ship_country,
    ]
    return ", ".join(part for part in parts if part)


def build_invoice(order: Order) -> BytesIO:
    """
    One row per style across the whole order, priced from the order lines.

    Billed on what is **packed**, not what was ordered, and counted the way
    `reconcile` counts it — a multi-part style is a unit only once every
    piece of it has a box. That keeps this document and the packing list
    agreeing on a single number, which is the pair a broker checks first.
    """
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Invoice"

    invoice_kit.set_widths(sheet)
    row = invoice_kit.write_heading(
        sheet,
        exporter=EXPORTER,
        consignee=[order.buyer_name or order.merchant.name],
        ship_to=[part for part in _address(order).split(", ") if part],
    )

    invoice_kit.write_column_headers(sheet, row)
    row += 1

    lines = {line.product_id: line for line in order.lines.select_related("product")}
    invoice = invoice_kit.Invoice()

    for reconciled in services.reconcile(order):
        if reconciled.packed == 0:
            continue
        line = lines[reconciled.product]
        product = line.product
        invoice.add(
            product.id,
            style_no=product.style_no,
            hts_code=_hsn(product),
            description=_customs(product),
            quantity=reconciled.packed,
            net_weight_kg=_unit_weight(product) * reconciled.packed,
            rate=line.rate_usd,
        )

    for serial, entry in enumerate(invoice.ordered(), start=1):
        invoice_kit.write_line(sheet, row, entry.row(serial))
        row += 1

    row = invoice_kit.write_totals(sheet, row, invoice)
    invoice_kit.write_footer(sheet, row, invoice, EXPORTER[0])

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
