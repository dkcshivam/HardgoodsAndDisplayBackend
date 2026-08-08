"""
The packing list as the shipping desk sends it: one row per thing inside a
carton, with the carton's own figures on the row that opens it, so a carton
is never counted twice when the columns are summed.
"""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .models import Order

# label, width, number format
COLUMNS = [
    ("Carton No", 13, None),
    ("Style No", 20, None),
    ("Color", 16, None),
    ("Description", 36, None),
    ("Qty", 7, "0"),
    ("Net Wt (kg)", 12, "0.000"),
    ("Gross Wt (kg)", 13, "0.000"),
    ("L (in)", 9, "0.00"),
    ("W (in)", 9, "0.00"),
    ("H (in)", 9, "0.00"),
    ("CBM", 10, "0.0000"),
]

TOTALLED = {"Qty", "Net Wt (kg)", "Gross Wt (kg)", "CBM"}

HEADER_FILL = PatternFill("solid", fgColor="EEF1FF")
RULE = Side(style="thin", color="D8DCE6")
BORDER = Border(left=RULE, right=RULE, top=RULE, bottom=RULE)


def packing_list_filename(order: Order) -> str:
    return f"packing-list-{order.number}.xlsx"


def build_packing_list(order: Order) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = order.number

    for index, (label, width, _) in enumerate(COLUMNS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width

    row = _write_heading(sheet, order)
    header_row = row + 1
    _write_column_headers(sheet, header_row)

    row = header_row + 1
    first_data_row = row

    # Colour is a property of this order, not of the product recipe.
    colors = {line.product_id: line.color for line in order.lines.all()}

    cartons = order.cartons.prefetch_related(
        "contents__product", "contents__part"
    ).all()

    for carton in cartons:
        contents = list(carton.contents.all())
        if not contents:
            _write_row(sheet, row, _carton_only_row(carton))
            row += 1
            continue

        for position, content in enumerate(contents):
            opens_carton = position == 0
            _write_row(
                sheet,
                row,
                [
                    carton.carton_no if opens_carton else "",
                    content.product.style_no,
                    colors.get(content.product_id, ""),
                    _describe(content),
                    content.quantity,
                    content.net_weight_kg,
                    carton.gross_weight_kg if opens_carton else None,
                    carton.length_in if opens_carton else None,
                    carton.width_in if opens_carton else None,
                    carton.height_in if opens_carton else None,
                    carton.cbm if opens_carton else None,
                ],
            )
            row += 1

    _write_totals(sheet, row, first_data_row, len(cartons))
    sheet.freeze_panes = sheet.cell(row=first_data_row, column=1)

    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


def _write_heading(sheet, order: Order) -> int:
    title = sheet.cell(row=1, column=1, value="PACKING LIST")
    title.font = Font(bold=True, size=15)

    facts = [
        ("Order", order.number),
        ("Name", order.name),
        ("Merchant", order.merchant.name),
        ("Buyer", order.buyer_name),
        ("Ship to", _address(order)),
        ("Status", order.get_status_display()),
    ]

    row = 2
    for label, value in facts:
        if not value:
            continue
        sheet.cell(row=row, column=1, value=label).font = Font(bold=True)
        sheet.cell(row=row, column=2, value=value)
        row += 1

    return row


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


def _write_column_headers(sheet, row: int) -> None:
    for index, (label, _, _) in enumerate(COLUMNS, start=1):
        cell = sheet.cell(row=row, column=index, value=label)
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
        cell.border = BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center")


def _describe(content) -> str:
    if content.description:
        return content.description
    if content.part_id:
        return f"{content.product.description} — {content.part.name}"
    return content.product.description


def _carton_only_row(carton) -> list:
    return [
        carton.carton_no,
        "",
        "",
        "(empty carton)",
        None,
        None,
        carton.gross_weight_kg,
        carton.length_in,
        carton.width_in,
        carton.height_in,
        carton.cbm,
    ]


def _write_row(sheet, row: int, values: list) -> None:
    for index, (value, (_, _, number_format)) in enumerate(
        zip(values, COLUMNS), start=1
    ):
        cell = sheet.cell(row=row, column=index, value=value)
        cell.border = BORDER
        if number_format:
            cell.number_format = number_format
            cell.alignment = Alignment(horizontal="right")


def _write_totals(sheet, row: int, first_data_row: int, carton_count: int) -> None:
    if row <= first_data_row:
        return

    last = row - 1
    label = sheet.cell(
        row=row,
        column=1,
        value=f"TOTAL · {carton_count} carton{'s' if carton_count != 1 else ''}",
    )
    label.font = Font(bold=True)

    # Summed with formulas so the sheet stays true after a manual edit.
    # Dimensions are deliberately not totalled — a sum of lengths means nothing.
    for index, (label_text, _, number_format) in enumerate(COLUMNS, start=1):
        if label_text not in TOTALLED:
            continue
        column = get_column_letter(index)
        cell = sheet.cell(
            row=row, column=index, value=f"=SUM({column}{first_data_row}:{column}{last})"
        )
        cell.font = Font(bold=True)
        cell.border = Border(top=Side(style="double", color="9AA2B1"))
        cell.number_format = number_format or "0"
        cell.alignment = Alignment(horizontal="right")
