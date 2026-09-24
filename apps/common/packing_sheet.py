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
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# label, width, number format
#
# The order and the wording follow the packing list the shipping desk already
# sends out by hand: what is in the box, then its three weights, then the box
# itself. Every figure describes **one** box, however many boxes the row
# stands for — the footer carries the shipment.
COLUMNS = [
    ("Carton Nos", 20, None),
    ("Cartons", 8, "0"),
    ("Style No", 18, None),
    ("Customs Description", 34, None),
    ("Qty / Box", 9, "0"),
    ("Units", 8, None),
    ("NNW (kg)", 11, "0.000"),
    ("N.W. (kg)", 11, "0.000"),
    ("G.W. (kg)", 11, "0.000"),
    ("L (cm)", 9, "0.00"),
    ("W (cm)", 9, "0.00"),
    ("H (cm)", 9, "0.00"),
    ("CBM", 10, "0.0000"),
]

# What the footer fills in. Not a column sum: a row standing for twelve
# identical boxes prints one box's figures and has to count as twelve, so
# these are worked out from the grouping instead. Dimensions total to nothing
# meaningful and are left blank.
TOTALLED = {
    "Cartons",
    "Qty / Box",
    "NNW (kg)",
    "N.W. (kg)",
    "G.W. (kg)",
    "CBM",
}

CM_PER_INCH = Decimal("2.54")
CM_PLACES = Decimal("0.01")
CUBIC_CM_PER_CBM = Decimal("1000000")
CBM_PLACES = Decimal("0.0001")


def cm(inches) -> Decimal | None:
    """
    Inches as the sheet prints them. Two places, because an inch is exactly
    2.54 cm — a whole-inch box converts without any rounding at all, and the
    CBM below then matches the one the app worked out in inches.
    """
    if inches is None:
        return None
    return (Decimal(inches) * CM_PER_INCH).quantize(
        CM_PLACES, rounding=ROUND_HALF_UP
    )


def cbm_from_cm(length_in, width_in, height_in) -> Decimal | None:
    """
    Worked from the centimetres actually printed rather than from the inches
    behind them, so a broker who multiplies the three numbers on the page
    arrives at the fourth.
    """
    sides = [cm(value) for value in (length_in, width_in, height_in)]
    if any(side is None for side in sides):
        return None
    length, width, height = sides
    return (length * width * height / CUBIC_CM_PER_CBM).quantize(CBM_PLACES)

@dataclass(frozen=True)
class Layout:
    """
    Which columns a sheet prints, and which of them carry a total.

    `Group.rows()` always builds the full canonical row above; a layout that
    prints something else — Display drops the carton count, because its rows
    are already blocked under the store they ship to — takes the columns it
    wants, so the grouping never has to know.
    """

    columns: list
    totalled: set


HEADER_FILL = PatternFill("solid", fgColor="EEF1FF")
GROUP_FILL = PatternFill("solid", fgColor="F5F6FA")
RULE = Side(style="thin", color="D8DCE6")
BORDER = Border(left=RULE, right=RULE, top=RULE, bottom=RULE)

# A box's rows read as one thing, so the rule that opens a box is heavier
# than the ones between its own styles.
EDGE = Side(style="medium", color="8B93A3")

#: What a sheet prints unless it says otherwise — Hardgoods uses this as is.
BASE = Layout(COLUMNS, TOTALLED)


# ── Grouping ─────────────────────────────────────────────────────────


@dataclass
class Group:
    """Cartons that are the same box holding the same thing, so one row."""

    contents: list
    cartons: list = field(default_factory=list)
    # Set where the document numbers its own rows; empty prints the numbers
    # stored on the cartons.
    label: str | int = ""

    def rows(self) -> list[list]:
        count = len(self.cartons)
        sample = self.cartons[0]
        label = self.label or carton_range(self.cartons)

        if not self.contents:
            return [empty_carton_row(sample, label)]

        built = []
        for position, content in enumerate(self.contents):
            # Only the first row of a box carries the box's own figures. A
            # carton holding six different things would otherwise state its
            # weight six times, and read as six boxes.
            opens = position == 0
            built.append(
                [
                    label if opens else "",
                    count if opens else None,
                    content.product.style_no,
                    describe(content),
                    content.quantity,
                    unit_label(content),
                    nnw(content),
                    sample.net_weight_kg if opens else None,
                    sample.gross_weight_kg if opens else None,
                    cm(sample.length_in) if opens else None,
                    cm(sample.width_in) if opens else None,
                    cm(sample.height_in) if opens else None,
                    cbm_from_cm(
                        sample.length_in, sample.width_in, sample.height_in
                    )
                    if opens
                    else None,
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


def number_groups(groups: list[Group], start: int = 1) -> int:
    """
    Number the rows in the order the sheet writes them, and hand back the
    next free number.

    `carton_no` runs in step order, and a sheet blocked by store reads those
    out of sequence — store 118 printing `BOX-001 – BOX-002, BOX-006` above a
    store whose run starts at 003. Numbering as we write gives every row one
    unbroken run and the page one ascending column. `start` threads across the
    blocks so the shipment keeps a single sequence (§10.6).

    Plain numbers, as the shipping desk writes them: a lone box is the number
    itself, so Excel stores it as one, and a run reads `10 – 14`.
    """
    for group in groups:
        last = start + len(group.cartons) - 1
        group.label = start if start == last else f"{start} – {last}"
        start = last + 1
    return start


def times(value: Decimal | None, count: int) -> Decimal | None:
    return None if value is None else value * count


def unit_label(content) -> str:
    """`pcs` on the record, `PCS` on a customs document."""
    return (content.unit or "").upper()


WEIGHT_PLACES = Decimal("0.001")


def nnw(content) -> Decimal | None:
    """
    The goods alone — unit weight times how many are in the box, with no
    packing material and no carton.

    `content.net_weight_kg` cannot stand in for this: Hardgoods folds the
    padding into it and Display does not, so the column would mean two
    different things on two documents the same desk reads.
    """
    piece = content.part if content.part_id else content.product
    weight = getattr(piece, "product_weight_kg", None)
    if weight is None:
        return None
    return (Decimal(weight) * (content.quantity or 0)).quantize(WEIGHT_PLACES)


@dataclass
class Totals:
    """
    What the shipment comes to, gathered as the rows are written.

    It cannot be a column sum. Every printed figure is one box's, and a row
    may stand for twelve of them, so each group is counted by its run.
    """

    cartons: int = 0
    quantity: int = 0
    nnw_kg: Decimal = Decimal("0")
    net_kg: Decimal = Decimal("0")
    gross_kg: Decimal = Decimal("0")
    cbm: Decimal = Decimal("0")

    def add(self, group: "Group") -> None:
        count = len(group.cartons)
        sample = group.cartons[0]
        self.cartons += count

        for content in group.contents:
            self.quantity += (content.quantity or 0) * count
            self.nnw_kg += (nnw(content) or Decimal("0")) * count

        self.net_kg += (sample.net_weight_kg or Decimal("0")) * count
        self.gross_kg += (sample.gross_weight_kg or Decimal("0")) * count
        volume = cbm_from_cm(sample.length_in, sample.width_in, sample.height_in)
        self.cbm += (volume or Decimal("0")) * count

    def merge(self, other: "Totals") -> None:
        self.cartons += other.cartons
        self.quantity += other.quantity
        self.nnw_kg += other.nnw_kg
        self.net_kg += other.net_kg
        self.gross_kg += other.gross_kg
        self.cbm += other.cbm

    def by_column(self) -> dict:
        return {
            "Cartons": self.cartons,
            "Total No of Boxes": self.cartons,
            "Qty / Box": self.quantity,
            "NNW (kg)": self.nnw_kg,
            "N.W. (kg)": self.net_kg,
            "G.W. (kg)": self.gross_kg,
            "CBM": self.cbm,
        }


def describe(content) -> str:
    """
    The customs wording where there is any, and the nearest thing to it where
    there is not. A blank cell here is a document a broker cannot clear, and
    a Display product often carries only a style name.
    """
    if content.description:
        return content.description
    if content.part_id:
        part = content.part
        return part.customs_description or f"{_names(content.product)} — {part.name}"
    return _names(content.product)


def _names(product) -> str:
    return (
        product.customs_description
        or getattr(product, "style_name", "")
        or product.description
    )


def empty_carton_row(carton, label: str | None = None) -> list:
    return [
        label if label is not None else carton_range([carton]),
        1,
        "",
        "(empty carton)",
        None,
        "",
        None,
        carton.net_weight_kg,
        carton.gross_weight_kg,
        cm(carton.length_in),
        cm(carton.width_in),
        cm(carton.height_in),
        cbm_from_cm(carton.length_in, carton.width_in, carton.height_in),
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


def write_row(
    sheet, row: int, values: list, layout: Layout = None, opens: bool = False
) -> None:
    """`opens` draws the heavier rule that separates one box from the last."""
    layout = layout or BASE
    border = (
        Border(left=RULE, right=RULE, top=EDGE, bottom=RULE) if opens else BORDER
    )
    for index, (value, (_, _, number_format)) in enumerate(
        zip(values, layout.columns), start=1
    ):
        cell = sheet.cell(row=row, column=index, value=value)
        cell.border = border
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
    totals: Totals,
    label: str,
    layout: Layout = None,
) -> None:
    """
    Values, not `=SUM()` formulas. The columns above hold one box's figures
    and a row may stand for twelve, so nothing on the page adds up to what
    ships — `Totals` counts the boxes and these are what it reached.
    """
    layout = layout or BASE
    if totals.cartons == 0:
        return

    heading = sheet.cell(row=row, column=1, value=label)
    heading.font = Font(bold=True)

    figures = totals.by_column()
    for index, (label_text, _, number_format) in enumerate(layout.columns, start=1):
        if label_text not in layout.totalled:
            continue
        cell = sheet.cell(row=row, column=index, value=figures.get(label_text))
        cell.font = Font(bold=True)
        cell.border = Border(top=Side(style="double", color="9AA2B1"))
        cell.number_format = number_format or "0"
        cell.alignment = Alignment(horizontal="right")


# ── Header grid for export packing list ──────────────────────────────

THIN_RULE = Side(style="thin", color="000000")

YELLOW_HEX = "EFE924"
YELLOW_FILL = PatternFill("solid", fgColor=YELLOW_HEX)
WHITE_FILL = PatternFill("solid", fgColor="FFFFFF")

HDR_LABEL_FONT = Font(name="Calibri", size=8, bold=True, color="000000")
HDR_VALUE_FONT = Font(name="Calibri", size=9, bold=False, color="000000")
HDR_VALUE_BOLD = Font(name="Calibri", size=9, bold=True, color="000000")
HDR_STAT_FONT = Font(name="Calibri", size=8.5, bold=True, color="000000")
HDR_TITLE_FONT = Font(name="Calibri", size=11, bold=True, italic=True, color="000000")

DEFAULT_PACKING_LIST_HEADER = {
    "highlight_static": True,
    "exporter": [
        "DKC EXPORTS PVT. LTD.",
        "A-4, SHIV MARG,GREEN AVN. , CHURCH ROAD",
        "VASANT KUNJ , NEW DELHI 110070",
        "INDIA",
        "",
        "Tel- + 9111 26124358",
    ],
    "exporter_ref_no": "IEC No 0506081460",
    "gstin": "07AACCD0416A1ZJ",
    "consignee": [
        "URBAN OUTFITTERS INC",
        "5000 SOUTH BROAD STREET",
        "PHILADELPHIA",
        "PA 19112-1495",
        "USA",
        "",
        "PH:-(215) 454-5500",
        "FAX:-(215) 454-4660",
    ],
    "statutory_details": [
        ("State of Origin Code", "07"),
        ("District of Origin Code", "84"),
        ("SQC", "PCS"),
        ("Pref. Agreements", "GSTP"),
        ("GST Comp. Cess", "N/A"),
        ("STATEMENT TYPE = DEC", "0"),
        ("STATEMENT CODE = RD001", "0"),
    ],
    "country_of_origin": "INDIA",
    "pre_carriage_by": "ROAD",
    "terms_and_marks": [
        ("TERM OF DELIVERY OF PAYMENT", "FOB"),
        ("PAYMENT BY", "LC"),
        ("SHIPPING MARK", "URBAN OUTFITTERS INC"),
        ("SHIPPING LINE", ""),
        ("CONTAINER NO", ""),
    ],
}


def draw_box(
    sheet,
    start_row: int,
    start_col: int,
    end_row: int,
    end_col: int,
    fill=None,
    top_rule=THIN_RULE,
    bottom_rule=THIN_RULE,
    left_rule=THIN_RULE,
    right_rule=THIN_RULE,
):
    """Draws perimeter borders for a box range and applies fill to every cell."""
    for r in range(start_row, end_row + 1):
        for c in range(start_col, end_col + 1):
            cell = sheet.cell(row=r, column=c)
            cell.border = Border(
                top=top_rule if r == start_row else None,
                bottom=bottom_rule if r == end_row else None,
                left=left_rule if c == start_col else None,
                right=right_rule if c == end_col else None,
            )
            if fill:
                cell.fill = fill


def write_block(
    sheet,
    label_row: int,
    content_start_row: int,
    content_end_row: int,
    start_col: int,
    end_col: int,
    label: str,
    value: str,
    fill=None,
    val_font=HDR_VALUE_FONT,
    val_align=None,
):
    """
    Writes a section with small bold label on top and value below it,
    surrounded by a single outer border box.
    """
    if start_col != end_col:
        sheet.merge_cells(
            start_row=label_row,
            start_column=start_col,
            end_row=label_row,
            end_column=end_col,
        )
    lbl_cell = sheet.cell(row=label_row, column=start_col, value=label)
    lbl_cell.font = HDR_LABEL_FONT
    lbl_cell.alignment = Alignment(horizontal="left", vertical="center")

    if content_start_row != content_end_row or start_col != end_col:
        sheet.merge_cells(
            start_row=content_start_row,
            start_column=start_col,
            end_row=content_end_row,
            end_column=end_col,
        )
    val_cell = sheet.cell(
        row=content_start_row, column=start_col, value=value or None
    )
    val_cell.font = val_font
    val_cell.alignment = val_align or Alignment(
        horizontal="left", vertical="top", wrap_text=True
    )

    draw_box(sheet, label_row, start_col, content_end_row, end_col, fill=fill)


def get_column_boundaries(last_col: int) -> dict:
    if last_col <= 13:
        # Hardgoods layout (13 columns)
        s1_start, s1_end = 1, 3
        s1_sub1_start, s1_sub1_end = 1, 1
        s1_sub2_start, s1_sub2_end = 2, 3

        s2_start, s2_end = 4, 7
        s2_sub1_start, s2_sub1_end = 4, 5
        s2_sub2_start, s2_sub2_end = 6, 7

        s3_start, s3_end = 8, last_col
        s3_gstin_lbl_start, s3_gstin_lbl_end = 8, 9
        s3_gstin_val_start, s3_gstin_val_end = 10, last_col
    else:
        # Display layout (18 columns)
        s1_start, s1_end = 1, 5
        s1_sub1_start, s1_sub1_end = 1, 2
        s1_sub2_start, s1_sub2_end = 3, 5

        s2_start, s2_end = 6, 11
        s2_sub1_start, s2_sub1_end = 6, 8
        s2_sub2_start, s2_sub2_end = 9, 11

        s3_start, s3_end = 12, last_col
        s3_gstin_lbl_start, s3_gstin_lbl_end = 12, 13
        s3_gstin_val_start, s3_gstin_val_end = 14, last_col

    return {
        "s1_start": s1_start,
        "s1_end": s1_end,
        "s1_sub1_start": s1_sub1_start,
        "s1_sub1_end": s1_sub1_end,
        "s1_sub2_start": s1_sub2_start,
        "s1_sub2_end": s1_sub2_end,
        "s2_start": s2_start,
        "s2_end": s2_end,
        "s2_sub1_start": s2_sub1_start,
        "s2_sub1_end": s2_sub1_end,
        "s2_sub2_start": s2_sub2_start,
        "s2_sub2_end": s2_sub2_end,
        "s3_start": s3_start,
        "s3_end": s3_end,
        "s3_gstin_lbl_start": s3_gstin_lbl_start,
        "s3_gstin_lbl_end": s3_gstin_lbl_end,
        "s3_gstin_val_start": s3_gstin_val_start,
        "s3_gstin_val_end": s3_gstin_val_end,
    }


def draw_packing_header(
    sheet, last_col: int, order_title: str = "", cfg: dict = None
) -> int:
    cfg = cfg or getattr(settings, "PACKING_LIST_HEADER", DEFAULT_PACKING_LIST_HEADER)
    highlight = cfg.get("highlight_static", True)
    y_fill = YELLOW_FILL if highlight else None
    w_fill = WHITE_FILL

    b = get_column_boundaries(last_col)

    # ── ROW 1 to 5: TOP SECTION ─────────────────────────────────────
    # Exporter (Row 1..5)
    exporter_lines = cfg.get("exporter", DEFAULT_PACKING_LIST_HEADER["exporter"])
    exporter_text = "\n".join(exporter_lines)
    write_block(
        sheet,
        1,
        2,
        5,
        b["s1_start"],
        b["s1_end"],
        label="Exporter",
        value=exporter_text,
        fill=y_fill,
    )

    # Invoice No & Date (Row 1..2)
    write_block(
        sheet,
        1,
        2,
        2,
        b["s2_sub1_start"],
        b["s2_sub1_end"],
        label="Invoice No & Date",
        value="",
        fill=w_fill,
    )
    # P.O. No. (Row 3)
    if b["s2_sub1_start"] != b["s2_sub1_end"]:
        sheet.merge_cells(
            start_row=3,
            start_column=b["s2_sub1_start"],
            end_row=3,
            end_column=b["s2_sub1_end"],
        )
    po_cell = sheet.cell(row=3, column=b["s2_sub1_start"], value="P.O. No.")
    po_cell.font = HDR_LABEL_FONT
    po_cell.alignment = Alignment(horizontal="left", vertical="center")
    draw_box(sheet, 3, b["s2_sub1_start"], 3, b["s2_sub1_end"], fill=w_fill)

    # Exporter's Ref No (Row 1..3)
    write_block(
        sheet,
        1,
        2,
        3,
        b["s2_sub2_start"],
        b["s2_sub2_end"],
        label="Exporter's Ref No",
        value=cfg.get(
            "exporter_ref_no", DEFAULT_PACKING_LIST_HEADER["exporter_ref_no"]
        ),
        fill=y_fill,
    )

    # Other Reference (Row 4..5)
    write_block(
        sheet,
        4,
        5,
        5,
        b["s2_start"],
        b["s2_end"],
        label="Other Reference",
        value="",
        fill=w_fill,
    )

    # LC No (Row 1..3)
    write_block(
        sheet,
        1,
        2,
        3,
        b["s3_start"],
        b["s3_end"],
        label="LC No",
        value="",
        fill=w_fill,
    )

    # GSTIN (Row 4..5)
    # GSTIN label box
    sheet.merge_cells(
        start_row=4,
        start_column=b["s3_gstin_lbl_start"],
        end_row=5,
        end_column=b["s3_gstin_lbl_end"],
    )
    gst_lbl = sheet.cell(row=4, column=b["s3_gstin_lbl_start"], value="GSTIN")
    gst_lbl.font = HDR_LABEL_FONT
    gst_lbl.alignment = Alignment(horizontal="center", vertical="center")
    draw_box(sheet, 4, b["s3_gstin_lbl_start"], 5, b["s3_gstin_lbl_end"], fill=y_fill)

    # GSTIN value box
    sheet.merge_cells(
        start_row=4,
        start_column=b["s3_gstin_val_start"],
        end_row=5,
        end_column=b["s3_end"],
    )
    gst_val = sheet.cell(
        row=4,
        column=b["s3_gstin_val_start"],
        value=cfg.get("gstin", DEFAULT_PACKING_LIST_HEADER["gstin"]),
    )
    gst_val.font = HDR_VALUE_BOLD
    gst_val.alignment = Alignment(horizontal="center", vertical="center")
    draw_box(sheet, 4, b["s3_gstin_val_start"], 5, b["s3_end"], fill=y_fill)

    for r in range(1, 6):
        sheet.row_dimensions[r].height = 15

    # ── ROW 6 to 14: MIDDLE SECTION ──────────────────────────────────
    # Consignee (Row 6..14)
    consignee_lines = cfg.get("consignee", DEFAULT_PACKING_LIST_HEADER["consignee"])
    consignee_text = "\n".join(consignee_lines)
    write_block(
        sheet,
        6,
        7,
        14,
        b["s1_start"],
        b["s1_end"],
        label="Consignee",
        value=consignee_text,
        fill=y_fill,
    )

    # Other Consignee (Shipp To-) (Row 6..12)
    write_block(
        sheet,
        6,
        7,
        12,
        b["s2_start"],
        b["s2_end"],
        label="Other Consignee (Shipp To-)",
        value="",
        fill=w_fill,
    )

    # Country of Origin of Goods (Row 13..14)
    write_block(
        sheet,
        13,
        14,
        14,
        b["s2_start"],
        b["s2_end"],
        label="COUNTRY OF ORIGIN OF GOODS",
        value=cfg.get(
            "country_of_origin", DEFAULT_PACKING_LIST_HEADER["country_of_origin"]
        ),
        fill=y_fill,
        val_align=Alignment(horizontal="left", vertical="center"),
    )

    # Statutory details box (Row 6..12, 7 rows in Section 3)
    stat_items = cfg.get(
        "statutory_details", DEFAULT_PACKING_LIST_HEADER["statutory_details"]
    )
    for idx, (label, val) in enumerate(stat_items):
        r = 6 + idx
        # label
        if b["s3_start"] != b["s3_gstin_lbl_end"]:
            sheet.merge_cells(
                start_row=r,
                start_column=b["s3_start"],
                end_row=r,
                end_column=b["s3_gstin_lbl_end"],
            )
        sl_cell = sheet.cell(row=r, column=b["s3_start"], value=label)
        sl_cell.font = HDR_STAT_FONT
        sl_cell.alignment = Alignment(horizontal="left", vertical="center")

        # value
        if b["s3_gstin_val_start"] != b["s3_end"]:
            sheet.merge_cells(
                start_row=r,
                start_column=b["s3_gstin_val_start"],
                end_row=r,
                end_column=b["s3_end"],
            )
        sv_cell = sheet.cell(row=r, column=b["s3_gstin_val_start"], value=val)
        sv_cell.font = HDR_STAT_FONT
        sv_cell.alignment = Alignment(horizontal="center", vertical="center")

    draw_box(sheet, 6, b["s3_start"], 12, b["s3_end"], fill=y_fill)

    # Country of Final Destination (Row 13..14)
    write_block(
        sheet,
        13,
        14,
        14,
        b["s3_start"],
        b["s3_end"],
        label="COUNTRY OF FINAL DESTINATION",
        value="",
        fill=w_fill,
        val_align=Alignment(horizontal="left", vertical="center"),
    )

    for r in range(6, 15):
        sheet.row_dimensions[r].height = 14

    # ── ROW 15 to 20: TRANSPORT & TERMS SECTION ──────────────────────
    # Transport left column 1 & 2
    # Row 15..16: Pre Carriage By / Place of Receipt
    write_block(
        sheet,
        15,
        16,
        16,
        b["s1_sub1_start"],
        b["s1_sub1_end"],
        label="PRE CARRIAGE BY",
        value=cfg.get(
            "pre_carriage_by", DEFAULT_PACKING_LIST_HEADER["pre_carriage_by"]
        ),
        fill=y_fill,
        val_align=Alignment(horizontal="left", vertical="center"),
    )
    write_block(
        sheet,
        15,
        16,
        16,
        b["s1_sub2_start"],
        b["s1_sub2_end"],
        label="PLACE OF RECEIPT",
        value="",
        fill=w_fill,
        val_align=Alignment(horizontal="left", vertical="center"),
    )

    # Row 17..18: Vessel/Flight No / Port of Loading
    write_block(
        sheet,
        17,
        18,
        18,
        b["s1_sub1_start"],
        b["s1_sub1_end"],
        label="VESSEL/FLIGHT NO",
        value="",
        fill=w_fill,
        val_align=Alignment(horizontal="left", vertical="center"),
    )
    write_block(
        sheet,
        17,
        18,
        18,
        b["s1_sub2_start"],
        b["s1_sub2_end"],
        label="PORT OF LOADING",
        value="",
        fill=w_fill,
        val_align=Alignment(horizontal="left", vertical="center"),
    )

    # Row 19..20: Port of Discharge / Final Destination
    write_block(
        sheet,
        19,
        20,
        20,
        b["s1_sub1_start"],
        b["s1_sub1_end"],
        label="PORT OF DISCHARGE",
        value="",
        fill=w_fill,
        val_align=Alignment(horizontal="left", vertical="center"),
    )
    write_block(
        sheet,
        19,
        20,
        20,
        b["s1_sub2_start"],
        b["s1_sub2_end"],
        label="FINAL DESTINATION",
        value="",
        fill=w_fill,
        val_align=Alignment(horizontal="left", vertical="center"),
    )

    # Terms & Marks (Middle + Right, cols s2_start to s3_end)
    terms_marks = cfg.get(
        "terms_and_marks", DEFAULT_PACKING_LIST_HEADER["terms_and_marks"]
    )
    for idx, (label, val) in enumerate(terms_marks):
        r = 15 + idx
        is_static = bool(val)
        fill = y_fill if is_static else w_fill

        if b["s2_start"] != b["s2_end"]:
            sheet.merge_cells(
                start_row=r,
                start_column=b["s2_start"],
                end_row=r,
                end_column=b["s2_end"],
            )
        tl_cell = sheet.cell(row=r, column=b["s2_start"], value=label)
        tl_cell.font = HDR_LABEL_FONT
        tl_cell.alignment = Alignment(horizontal="left", vertical="center")

        if b["s3_start"] != b["s3_end"]:
            sheet.merge_cells(
                start_row=r,
                start_column=b["s3_start"],
                end_row=r,
                end_column=b["s3_end"],
            )
        tv_cell = sheet.cell(row=r, column=b["s3_start"], value=val or None)
        tv_cell.font = HDR_VALUE_FONT
        tv_cell.alignment = Alignment(horizontal="left", vertical="center")

        if fill:
            for c in range(b["s2_start"], b["s3_end"] + 1):
                sheet.cell(row=r, column=c).fill = fill

    # Empty 6th line for padding row 20
    if b["s2_start"] != b["s2_end"]:
        sheet.merge_cells(
            start_row=20,
            start_column=b["s2_start"],
            end_row=20,
            end_column=b["s2_end"],
        )
    if b["s3_start"] != b["s3_end"]:
        sheet.merge_cells(
            start_row=20,
            start_column=b["s3_start"],
            end_row=20,
            end_column=b["s3_end"],
        )
    draw_box(sheet, 15, b["s2_start"], 20, b["s3_end"])

    for r in range(15, 21):
        sheet.row_dimensions[r].height = 14

    # ── ROW 21: TITLE ROW ────────────────────────────────────────────
    title_suffix = (order_title or "").strip()
    if title_suffix:
        upper_title = title_suffix.upper()
        if upper_title.startswith("PACKING LIST FOR"):
            title_text = upper_title
        elif upper_title.startswith("PACKING LIST"):
            title_text = upper_title
        elif upper_title.endswith("ITEMS"):
            title_text = f"PACKING LIST FOR {upper_title}"
        else:
            title_text = f"PACKING LIST FOR {upper_title} ITEMS"
    else:
        title_text = "PACKING LIST"

    sheet.merge_cells(start_row=21, start_column=1, end_row=21, end_column=last_col)
    t_cell = sheet.cell(row=21, column=1, value=title_text)
    t_cell.font = HDR_TITLE_FONT
    t_cell.alignment = Alignment(horizontal="left", vertical="center")
    draw_box(sheet, 21, 1, 21, last_col)
    sheet.row_dimensions[21].height = 24

    return 22  # row for column headers


# ── Document ─────────────────────────────────────────────────────────
#
# What the packing list says, with nothing about how it is drawn. The
# workbook and the print page both render this, so the .xlsx a broker files
# and the PDF the desk signs cannot drift apart.


@dataclass
class Block:
    """A run of rows under one banner — for Display, one store."""

    rows: list = field(default_factory=list)  # (values, opens)
    banner: str = ""
    subtotal_label: str = ""
    subtotal: "Totals | None" = None


@dataclass
class Document:
    title: str
    facts: list
    blocks: list
    total: Totals
    total_label: str
    layout: Layout = BASE
    order_title: str = ""


def write_document(sheet, doc: Document) -> None:
    set_widths(sheet, doc.layout)

    header_row = draw_packing_header(
        sheet,
        len(doc.layout.columns),
        order_title=doc.order_title or doc.title,
    )
    write_column_headers(sheet, header_row, doc.layout)
    row = header_row + 1
    first_data_row = row

    for block in doc.blocks:
        if block.banner:
            write_banner(sheet, row, block.banner, doc.layout)
            row += 1
        for values, opens in block.rows:
            write_row(sheet, row, values, doc.layout, opens=opens)
            row += 1
        if block.subtotal is not None:
            write_totals(
                sheet, row, block.subtotal, block.subtotal_label, doc.layout
            )
            row += 2

    write_totals(sheet, row, doc.total, doc.total_label, doc.layout)
    sheet.freeze_panes = sheet.cell(row=first_data_row, column=1)



def places(number_format: str | None) -> int | None:
    """Decimal places from an Excel format, so the page can round the same."""
    if not number_format:
        return None
    _, _, fraction = number_format.partition(".")
    return len(fraction)


def plain(value):
    """Decimals go out as numbers — the API does not stringify them."""
    if isinstance(value, Decimal):
        return float(value)
    return value


def _totals_row(totals: "Totals | None", layout: Layout) -> list | None:
    if totals is None or totals.cartons == 0:
        return None
    figures = totals.by_column()
    return [
        plain(figures.get(label)) if label in layout.totalled else None
        for label, _, _ in layout.columns
    ]


def document_json(doc: Document) -> dict:
    return {
        "title": doc.title,
        "facts": [
            {"label": label, "value": value} for label, value in doc.facts if value
        ],
        "columns": [
            {"label": label, "places": places(number_format)}
            for label, _, number_format in doc.layout.columns
        ],
        "blocks": [
            {
                "banner": block.banner,
                "rows": [
                    {"opens": opens, "values": [plain(value) for value in values]}
                    for values, opens in block.rows
                ],
                "subtotal_label": block.subtotal_label,
                "subtotal": _totals_row(block.subtotal, doc.layout),
            }
            for block in doc.blocks
        ],
        "total_label": doc.total_label,
        "total": _totals_row(doc.total, doc.layout),
    }
