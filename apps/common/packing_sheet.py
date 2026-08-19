"""
The shared machinery behind both packing lists: one row per distinct thing
packed rather than per carton, and the spreadsheet furniture around it.

Hardgoods and Display keep separate models and separate documents, but a
carton is a carton — the grouping, the carton-range notation and the column
layout are the same question in both, and a shipping desk reading one after
the other should not have to learn two conventions.

Everything here is duck-typed against a carton: `carton_no`, `contents`,
`gross_weight_kg`, `length_in`/`width_in`/`height_in`, `cbm`.
"""

import re
from dataclasses import dataclass, field
from decimal import Decimal

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

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

@dataclass(frozen=True)
class Layout:
    """
    Which columns a sheet prints, and which of them carry a total.

    `Group.rows()` always builds the full canonical row above; a layout that
    prints something else — Display prepends the store and drops the carton
    count — reorders that row itself, so the grouping never has to know.
    """

    columns: list
    totalled: set


HEADER_FILL = PatternFill("solid", fgColor="EEF1FF")
GROUP_FILL = PatternFill("solid", fgColor="F5F6FA")
RULE = Side(style="thin", color="D8DCE6")
BORDER = Border(left=RULE, right=RULE, top=RULE, bottom=RULE)

#: What a sheet prints unless it says otherwise — Hardgoods uses this as is.
BASE = Layout(COLUMNS, TOTALLED)


# ── Grouping ─────────────────────────────────────────────────────────


@dataclass
class Group:
    """Cartons that are the same box holding the same thing, so one row."""

    contents: list
    cartons: list = field(default_factory=list)

    def rows(self, color_for) -> list[list]:
        count = len(self.cartons)
        sample = self.cartons[0]

        if not self.contents:
            return [empty_carton_row(sample)]

        built = []
        for position, content in enumerate(self.contents):
            # A carton holding several different things repeats none of its
            # own figures, so the totals below cannot count it twice.
            opens = position == 0
            built.append(
                [
                    carton_range(self.cartons) if opens else "",
                    count if opens else None,
                    content.product.style_no,
                    color_for(content, sample),
                    describe(content),
                    content.quantity,
                    content.quantity * count,
                    content.net_weight_kg,
                    times(content.net_weight_kg, count),
                    sample.gross_weight_kg if opens else None,
                    times(sample.gross_weight_kg, count) if opens else None,
                    sample.length_in if opens else None,
                    sample.width_in if opens else None,
                    sample.height_in if opens else None,
                    sample.cbm if opens else None,
                    times(sample.cbm, count) if opens else None,
                ]
            )
        return built


def group_cartons(cartons: list) -> list[Group]:
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


def _key(carton, contents: list) -> tuple | None:
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


def carton_range(cartons: list) -> str:
    """
    `BOX-001 – BOX-012` for a run, and each run named when a hand-edited
    plan leaves gaps: `BOX-001 – BOX-003, BOX-007`.

    Every number a row covers is either printed or inside a printed run.
    A shorthand for the gaps would be shorter, but a range that has to be
    decoded is one somebody miscounts, and this document is read by people
    who will not ask.
    """
    labels = [(carton.carton_no or "").strip() for carton in cartons]
    if len(labels) == 1:
        return labels[0]

    numbered = [TRAILING_NUMBER.search(label) for label in labels]
    if not all(numbered):
        return ", ".join(labels)

    pairs = sorted(zip((int(match.group(1)) for match in numbered), labels))
    numbers = [number for number, _ in pairs]

    runs, start = [], 0
    for index in range(1, len(pairs) + 1):
        if index == len(pairs) or numbers[index] != numbers[index - 1] + 1:
            runs.append((start, index - 1))
            start = index

    return ", ".join(
        pairs[a][1] if a == b else f"{pairs[a][1]} – {pairs[b][1]}" for a, b in runs
    )


def times(value: Decimal | None, count: int) -> Decimal | None:
    return None if value is None else value * count


def describe(content) -> str:
    if content.description:
        return content.description
    if content.part_id:
        return f"{content.product.description} — {content.part.name}"
    return content.product.description


def empty_carton_row(carton) -> list:
    return [
        carton_range([carton]),
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


def set_widths(sheet, layout: Layout = None) -> None:
    layout = layout or BASE
    for index, (_, width, _) in enumerate(layout.columns, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width


def write_facts(sheet, row: int, facts: list[tuple[str, str]]) -> int:
    for label, value in facts:
        if not value:
            continue
        sheet.cell(row=row, column=1, value=label).font = Font(bold=True)
        sheet.cell(row=row, column=2, value=value)
        row += 1
    return row


def write_column_headers(sheet, row: int, layout: Layout = None) -> None:
    layout = layout or BASE
    for index, (label, _, _) in enumerate(layout.columns, start=1):
        cell = sheet.cell(row=row, column=index, value=label)
        cell.font = Font(bold=True)
        cell.fill = HEADER_FILL
        cell.border = BORDER
        cell.alignment = Alignment(
            horizontal="center", vertical="center", wrap_text=True
        )


def write_row(sheet, row: int, values: list, layout: Layout = None) -> None:
    layout = layout or BASE
    for index, (value, (_, _, number_format)) in enumerate(
        zip(values, layout.columns), start=1
    ):
        cell = sheet.cell(row=row, column=index, value=value)
        cell.border = BORDER
        if number_format:
            cell.number_format = number_format
            cell.alignment = Alignment(horizontal="right")


def write_banner(sheet, row: int, text: str, layout: Layout = None) -> None:
    """A full-width label opening a block — the store a run of rows is for."""
    layout = layout or BASE
    cell = sheet.cell(row=row, column=1, value=text)
    cell.font = Font(bold=True)
    cell.fill = GROUP_FILL
    for index in range(1, len(layout.columns) + 1):
        sheet.cell(row=row, column=index).fill = GROUP_FILL


def write_totals(
    sheet,
    row: int,
    ranges: list[tuple[int, int]],
    label: str,
    layout: Layout = None,
) -> None:
    """
    Summed with formulas rather than values, so the sheet stays true if
    somebody edits a quantity after it leaves here.

    `ranges` is the data rows to add up, given explicitly rather than as one
    span: a sheet blocked by store has subtotal rows in between, and a single
    span across them would add every carton twice.
    """
    layout = layout or BASE
    spans = [(a, b) for a, b in ranges if b >= a]
    if not spans:
        return

    heading = sheet.cell(row=row, column=1, value=label)
    heading.font = Font(bold=True)

    for index, (label_text, _, number_format) in enumerate(layout.columns, start=1):
        if label_text not in layout.totalled:
            continue
        column = get_column_letter(index)
        parts = ",".join(f"{column}{a}:{column}{b}" for a, b in spans)
        cell = sheet.cell(row=row, column=index, value=f"=SUM({parts})")
        cell.font = Font(bold=True)
        cell.border = Border(top=Side(style="double", color="9AA2B1"))
        cell.number_format = number_format or "0"
        cell.alignment = Alignment(horizontal="right")
