"""
The packing list as the shipping desk sends it: one row per distinct thing
packed, not per carton. Twelve identical cartons of one chair collapse to a
single row carrying their carton range and count, so the sheet is as long as
the order has different items rather than as long as it has boxes.

The grouping and the sheet furniture live in `apps/common/packing_sheet.py`,
shared with Display.
"""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font

from apps.common import packing_sheet as sheet_kit

from .models import Order


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

    # Colour is a property of this order, not of the product recipe.
    colors = {line.product_id: line.color for line in order.lines.all()}

    cartons = list(
        order.cartons.prefetch_related("contents__product", "contents__part")
    )

    for group in sheet_kit.group_cartons(cartons):
        for values in group.rows(lambda c, _carton: colors.get(c.product_id, "")):
            sheet_kit.write_row(sheet, row, values)
            row += 1

    count = len(cartons)
    sheet_kit.write_totals(
        sheet,
        row,
        [(first_data_row, row - 1)],
        f"TOTAL · {count} carton{'s' if count != 1 else ''}",
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
