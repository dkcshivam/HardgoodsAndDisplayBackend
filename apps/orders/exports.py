"""
The packing list as the shipping desk sends it: one row per distinct thing
packed, not per carton. Twelve identical cartons of one chair collapse to a
single row carrying their carton range and count, so the sheet is as long as
the order has different items rather than as long as it has boxes.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .models import Carton, CartonContent, Order

# label, width, number format
COLUMNS = [
    ("Carton Nos", 20, None),
    ("Cartons", 8, "0"),
    ("Style No", 18, None),
    ("Color", 15, None),
    ("Description", 32, None),
    ("Qty / Ctn", 9, "0"),
    ("Total Qty", 10, "0"),
    ("N.W. / Ctn (kg)", 14, "0.000"),
    ("Total N.W. (kg)", 14, "0.000"),
    ("G.W. / Ctn (kg)", 14, "0.000"),
    ("Total G.W. (kg)", 14, "0.000"),
    ("L (in)", 8, "0.00"),
    ("W (in)", 8, "0.00"),
    ("H (in)", 8, "0.00"),
    ("CBM / Ctn", 11, "0.0000"),
    ("Total CBM", 11, "0.0000"),
]

# Only the totals columns. Summing a per-carton figure would count one box
# once and twelve identical ones once as well; summing a dimension is
# meaningless whichever way the sheet is grouped.
TOTALLED = {
    "Cartons",
    "Total Qty",
    "Total N.W. (kg)",
    "Total G.W. (kg)",
    "Total CBM",
}

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

    cartons = list(
        order.cartons.prefetch_related("contents__product", "contents__part")
    )

    for group in _group(cartons):
        for values in group.rows(colors):
            _write_row(sheet, row, values)
            row += 1

    _write_totals(sheet, row, first_data_row, len(cartons))
    sheet.freeze_panes = sheet.cell(row=first_data_row, column=1)

    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


# ── Grouping ─────────────────────────────────────────────────────────


@dataclass
class Group:
    """Cartons that are the same box holding the same thing, so one row."""

    contents: list[CartonContent]
    cartons: list[Carton] = field(default_factory=list)

    def rows(self, colors: dict[int, str]) -> list[list]:
        count = len(self.cartons)
        sample = self.cartons[0]

        if not self.contents:
            return [_empty_carton_row(sample)]

        built = []
        for position, content in enumerate(self.contents):
            # A carton holding several different things repeats none of its
            # own figures, so the totals below cannot count it twice.
            opens = position == 0
            built.append(
                [
                    _carton_range(self.cartons) if opens else "",
                    count if opens else None,
                    content.product.style_no,
                    colors.get(content.product_id, ""),
                    _describe(content),
                    content.quantity,
                    content.quantity * count,
                    content.net_weight_kg,
                    _times(content.net_weight_kg, count),
                    sample.gross_weight_kg if opens else None,
                    _times(sample.gross_weight_kg, count) if opens else None,
                    sample.length_in if opens else None,
                    sample.width_in if opens else None,
                    sample.height_in if opens else None,
                    sample.cbm if opens else None,
                    _times(sample.cbm, count) if opens else None,
                ]
            )
        return built


def _group(cartons: list[Carton]) -> list[Group]:
    """
    Cartons collapse into one row when the box and its single content match
    on every printed field. A carton holding more than one thing stands
    alone — merging it would need every other carton to hold the same mix.
    """
    groups: dict[tuple, Group] = {}
    ordered: list[Group] = []

    for carton in cartons:
        contents = list(carton.contents.all())
        key = _key(carton, contents)

        group = groups.get(key) if key else None
        if group is None:
            group = Group(contents=contents)
            ordered.append(group)
            if key:
                groups[key] = group

        group.cartons.append(carton)

    return ordered


def _key(carton: Carton, contents: list[CartonContent]) -> tuple | None:
    """None for anything that must keep a row of its own."""
    if len(contents) != 1:
        return None

    content = contents[0]
    return (
        content.product_id,
        content.part_id,
        content.description,
        content.quantity,
        content.unit,
        content.net_weight_kg,
        carton.gross_weight_kg,
        carton.length_in,
        carton.width_in,
        carton.height_in,
    )


TRAILING_NUMBER = re.compile(r"(\d+)$")


def _carton_range(cartons: list[Carton]) -> str:
    """
    `CTN-001 – CTN-012` for a run.

    Auto-pack numbers a multi-part product's cartons one whole unit at a
    time, so a single part's boxes step evenly rather than run consecutively.
    Spelling all fifteen of them out fills the cell, so an even step is
    printed as `CTN-001 – CTN-029 (every 2nd)`. Anything less regular — a
    plan someone has edited by hand — falls back to listing its runs.
    """
    labels = [(carton.carton_no or "").strip() for carton in cartons]
    if len(labels) == 1:
        return labels[0]

    numbered = [TRAILING_NUMBER.search(label) for label in labels]
    if not all(numbered):
        return ", ".join(labels)

    pairs = sorted(zip((int(match.group(1)) for match in numbered), labels))
    numbers = [number for number, _ in pairs]
    first, last = pairs[0][1], pairs[-1][1]

    steps = {b - a for a, b in zip(numbers, numbers[1:])}
    if steps == {1}:
        return f"{first} – {last}"
    # Two cartons two apart read better as the pair than as a rule.
    if len(steps) == 1 and len(pairs) >= 3:
        return f"{first} – {last} (every {_ordinal(steps.pop())})"

    runs, start = [], 0
    for index in range(1, len(pairs) + 1):
        if index == len(pairs) or numbers[index] != numbers[index - 1] + 1:
            runs.append((start, index - 1))
            start = index

    return ", ".join(
        pairs[a][1] if a == b else f"{pairs[a][1]} – {pairs[b][1]}" for a, b in runs
    )


ORDINAL_SUFFIX = {1: "st", 2: "nd", 3: "rd"}


def _ordinal(number: int) -> str:
    if 11 <= number % 100 <= 13:
        return f"{number}th"
    return f"{number}{ORDINAL_SUFFIX.get(number % 10, 'th')}"


def _times(value: Decimal | None, count: int) -> Decimal | None:
    return None if value is None else value * count


def _describe(content: CartonContent) -> str:
    if content.description:
        return content.description
    if content.part_id:
        return f"{content.product.description} — {content.part.name}"
    return content.product.description


def _empty_carton_row(carton: Carton) -> list:
    return [
        _carton_range([carton]),
        1,
        "",
        "",
        "(empty carton)",
        None,
        None,
        None,
        None,
        carton.gross_weight_kg,
        carton.gross_weight_kg,
        carton.length_in,
        carton.width_in,
        carton.height_in,
        carton.cbm,
        carton.cbm,
    ]


# ── Sheet ────────────────────────────────────────────────────────────


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
        cell.alignment = Alignment(
            horizontal="center", vertical="center", wrap_text=True
        )


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
