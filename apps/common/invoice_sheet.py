"""
The commercial invoice, in the shape the shipping desk already sends.

One row per style across the whole shipment — the packing list says which box
a thing is in, this says what it is worth. The two are read side by side and
their quantities must agree, so both count what is **packed**, never what was
ordered.

The heading block is drawn but left empty. Invoice number, ports, vessel,
container and LC change per shipment and the app holds none of them; ruling
the boxes and labelling them is the useful half, and the desk fills the rest.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from io import BytesIO

from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter

MONEY = Decimal("0.01")
WEIGHT = Decimal("0.001")
ZERO = Decimal("0")

RULE = Side(style="thin", color="000000")
BOX = Border(left=RULE, right=RULE, top=RULE, bottom=RULE)
TITLE = Font(bold=True, size=14)
LABEL = Font(bold=True, size=8)
VALUE = Font(size=10)
HEAD = Font(bold=True, size=9)

# label, width, number format
COLUMNS = [
    ("Serial No", 9, "0"),
    ("Style No", 18, None),
    ("HTS Code", 14, None),
    ("Customs Description with Contents", 46, None),
    ("Qty in Pcs", 11, "0"),
    ("N.Wt. in Kgs.", 13, "0.000"),
    ("Rate in US$", 12, "0.00"),
    ("Amount in US$", 15, "0.00"),
]

SERIAL, STYLE, HTS, DESCRIPTION, QTY, NET, RATE, AMOUNT = range(8)

ORIGIN_LINE = "COUNTRY OF ORIGIN OF GOODS — INDIA"
IGST_NOTE = "Note: IGST is paid under the refund mechanism; no charge to the buyer."
SIGNATORY = "Authorised Signatory"
DECLARATION = [
    "We declare that this invoice shows the actual price of the goods",
    "described and that all particulars are true and correct.",
]


#: Left blank for the desk. Each is one labelled cell with room under it.
SHIPMENT_FIELDS = [
    ("Invoice No & Date", "P.O. No.", "L/C No"),
    ("Other Reference", "Buyer's Order No", "Country of Final Destination"),
    ("Pre-Carriage By", "Place of Receipt", "Vessel / Flight No"),
    ("Port of Loading", "Port of Discharge", "Final Destination"),
    ("Terms of Delivery", "Payment By", "Shipping Line"),
    ("Container No", "Shipping Mark", "Marks & Numbers"),
]


@dataclass
class Line:
    """One style, summed across every box it ships in."""

    style_no: str
    hts_code: str
    description: str
    quantity: int = 0
    net_weight_kg: Decimal = ZERO
    rate_usd: Decimal | None = None

    @property
    def amount_usd(self) -> Decimal | None:
        if self.rate_usd is None:
            return None
        return (self.rate_usd * self.quantity).quantize(MONEY)

    def row(self, serial: int) -> list:
        return [
            serial,
            self.style_no,
            self.hts_code,
            self.description,
            self.quantity,
            self.net_weight_kg.quantize(WEIGHT),
            self.rate_usd,
            self.amount_usd,
        ]


@dataclass
class Invoice:
    """Every style on the shipment, in style-number order."""

    lines: dict = field(default_factory=dict)

    def add(self, piece, style_no, hts_code, description, quantity, net_weight_kg, rate):
        line = self.lines.get(piece)
        if line is None:
            line = Line(
                style_no=style_no,
                hts_code=hts_code,
                description=description,
                rate_usd=rate,
            )
            self.lines[piece] = line
        # A style shipping in twenty boxes is still one invoice line.
        line.quantity += quantity
        line.net_weight_kg += net_weight_kg or ZERO
        return line

    def ordered(self) -> list[Line]:
        return sorted(self.lines.values(), key=lambda line: line.style_no)

    @property
    def total_quantity(self) -> int:
        return sum(line.quantity for line in self.lines.values())

    @property
    def total_net_weight_kg(self) -> Decimal:
        return sum(
            (line.net_weight_kg for line in self.lines.values()), start=ZERO
        ).quantize(WEIGHT)

    @property
    def total_amount_usd(self) -> Decimal:
        return sum(
            (line.amount_usd or ZERO for line in self.lines.values()), start=ZERO
        ).quantize(MONEY)

    @property
    def is_priced(self) -> bool:
        return any(line.rate_usd is not None for line in self.lines.values())


# ── Sheet ────────────────────────────────────────────────────────────


def set_widths(sheet) -> None:
    for index, (_, width, _) in enumerate(COLUMNS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width


def _span(sheet, row: int, first: int, last: int, label: str, value: str = "") -> None:
    """A labelled box: the caption small above, the value under it."""
    sheet.merge_cells(start_row=row, start_column=first, end_row=row, end_column=last)
    sheet.merge_cells(
        start_row=row + 1, start_column=first, end_row=row + 1, end_column=last
    )

    caption = sheet.cell(row=row, column=first, value=label)
    caption.font = LABEL
    caption.alignment = Alignment(horizontal="left", vertical="center")

    entry = sheet.cell(row=row + 1, column=first, value=value or None)
    entry.font = VALUE
    entry.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)

    for line in (row, row + 1):
        for column in range(first, last + 1):
            sheet.cell(row=line, column=column).border = BOX


def write_heading(sheet, exporter: list[str], consignee: list[str], ship_to: list[str]) -> int:
    """
    The letterhead. Parties are known; everything about the shipment is not,
    so those boxes are ruled and labelled and left for the desk to fill.
    """
    last = len(COLUMNS)

    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last)
    title = sheet.cell(row=1, column=1, value="COMMERCIAL INVOICE")
    title.font = TITLE
    title.alignment = Alignment(horizontal="center", vertical="center")
    sheet.row_dimensions[1].height = 24

    row = 2
    third = max(3, last // 3)
    _span(sheet, row, 1, third, "Exporter", "\n".join(exporter))
    _span(sheet, row, third + 1, last, "Consignee", "\n".join(consignee))
    sheet.row_dimensions[row + 1].height = 62
    row += 2

    _span(sheet, row, 1, third, "Other Consignee (Ship To)", "\n".join(ship_to))
    _span(sheet, row, third + 1, last, "Country of Origin of Goods", "INDIA")
    sheet.row_dimensions[row + 1].height = 48
    row += 2

    for group in SHIPMENT_FIELDS:
        edges = _thirds(last, len(group))
        for label, (first, stop) in zip(group, edges):
            _span(sheet, row, first, stop, label)
        row += 2

    return row


def _thirds(last: int, parts: int) -> list[tuple[int, int]]:
    """Column spans that divide the sheet's width evenly, to the last column."""
    width = last // parts
    edges = []
    start = 1
    for index in range(parts):
        stop = last if index == parts - 1 else start + width - 1
        edges.append((start, stop))
        start = stop + 1
    return edges


def write_column_headers(sheet, row: int) -> None:
    for index, (label, _, _) in enumerate(COLUMNS, start=1):
        cell = sheet.cell(row=row, column=index, value=label)
        cell.font = HEAD
        cell.border = BOX
        cell.alignment = Alignment(
            horizontal="center", vertical="center", wrap_text=True
        )
    sheet.row_dimensions[row].height = 30


def write_line(sheet, row: int, values: list) -> None:
    for index, (value, (_, _, number_format)) in enumerate(zip(values, COLUMNS), start=1):
        cell = sheet.cell(row=row, column=index, value=value)
        cell.border = BOX
        cell.font = VALUE
        if number_format:
            cell.number_format = number_format
            cell.alignment = Alignment(horizontal="right")
        else:
            cell.alignment = Alignment(vertical="center", wrap_text=True)


def write_totals(sheet, row: int, invoice: Invoice) -> int:
    figures = {
        QTY: invoice.total_quantity,
        NET: invoice.total_net_weight_kg,
        AMOUNT: invoice.total_amount_usd if invoice.is_priced else None,
    }

    sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=QTY)
    label = sheet.cell(row=row, column=1, value="TOTAL")
    label.font = Font(bold=True)
    label.alignment = Alignment(horizontal="right", vertical="center")

    for index, (_, _, number_format) in enumerate(COLUMNS):
        cell = sheet.cell(row=row, column=index + 1)
        cell.border = BOX
        if index in figures:
            cell.value = figures[index]
            cell.font = Font(bold=True)
            cell.number_format = number_format or "0"
            cell.alignment = Alignment(horizontal="right")
    return row + 1


def write_footer(sheet, row: int, invoice: Invoice, exporter_name: str) -> None:
    last = len(COLUMNS)
    row += 1

    sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=last)
    origin = sheet.cell(row=row, column=1, value=ORIGIN_LINE)
    origin.font = Font(bold=True)
    row += 2

    if invoice.is_priced:
        words = amount_in_words(invoice.total_amount_usd)
        sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=RATE)
        spelled = sheet.cell(
            row=row,
            column=1,
            value=f"TOTAL CHARGEABLE AMOUNT IN US DOLLAR — {words}",
        )
        spelled.font = Font(bold=True)
        amount = sheet.cell(row=row, column=last, value=invoice.total_amount_usd)
        amount.font = Font(bold=True)
        amount.number_format = "0.00"
        amount.alignment = Alignment(horizontal="right")
        row += 2

    sheet.merge_cells(start_row=row, start_column=1, end_row=row, end_column=last)
    sheet.cell(row=row, column=1, value=IGST_NOTE).font = Font(size=9)
    row += 2

    declaration = sheet.cell(row=row, column=1, value="Declaration:")
    declaration.font = Font(bold=True)
    signatory = sheet.cell(row=row, column=RATE, value=SIGNATORY)
    signatory.font = Font(bold=True)
    row += 1

    for text in DECLARATION:
        sheet.cell(row=row, column=1, value=text).font = Font(size=9)
        row += 1

    sheet.cell(row=row + 1, column=RATE, value=f"for {exporter_name}").font = Font(
        size=9
    )


# ── Amount in words ──────────────────────────────────────────────────

_UNITS = (
    "ZERO ONE TWO THREE FOUR FIVE SIX SEVEN EIGHT NINE TEN ELEVEN TWELVE "
    "THIRTEEN FOURTEEN FIFTEEN SIXTEEN SEVENTEEN EIGHTEEN NINETEEN"
).split()
_TENS = (
    "  TWENTY THIRTY FORTY FIFTY SIXTY SEVENTY EIGHTY NINETY".split()
)
_SCALES = [(1_000_000_000, "BILLION"), (1_000_000, "MILLION"), (1_000, "THOUSAND")]


def _under_thousand(number: int) -> str:
    if number < 20:
        return _UNITS[number]
    if number < 100:
        tens, rest = divmod(number, 10)
        word = _TENS[tens - 2]
        return f"{word} {_UNITS[rest]}" if rest else word
    hundreds, rest = divmod(number, 100)
    word = f"{_UNITS[hundreds]} HUNDRED"
    return f"{word} {_under_thousand(rest)}" if rest else word


def _spell(number: int) -> str:
    if number == 0:
        return _UNITS[0]
    parts = []
    for size, name in _SCALES:
        if number >= size:
            count, number = divmod(number, size)
            parts.append(f"{_under_thousand(count)} {name}")
    if number:
        parts.append(_under_thousand(number))
    return " ".join(parts)


def amount_in_words(amount: Decimal) -> str:
    """`SIXTEEN THOUSAND ONE HUNDRED NINETY THREE AND 18/100 ONLY`."""
    whole = int(amount)
    cents = int((amount - whole) * 100)
    words = _spell(whole)
    return f"{words} AND {cents:02d}/100 ONLY"



# ── Document ─────────────────────────────────────────────────────────
#
# The invoice as data. The workbook and the print page render this same
# object, so the sheet emailed to the broker and the PDF signed at the desk
# carry identical figures and identical wording.


@dataclass
class Document:
    exporter: list
    consignee: list
    ship_to: list
    invoice: Invoice
    origin: str = "INDIA"


def write_document(sheet, doc: Document) -> None:
    set_widths(sheet)
    row = write_heading(sheet, doc.exporter, doc.consignee, doc.ship_to)

    write_column_headers(sheet, row)
    row += 1

    for serial, line in enumerate(doc.invoice.ordered(), start=1):
        write_line(sheet, row, line.row(serial))
        row += 1

    row = write_totals(sheet, row, doc.invoice)
    write_footer(sheet, row, doc.invoice, doc.exporter[0])


def _places(number_format: str | None) -> int | None:
    if not number_format:
        return None
    _, _, fraction = number_format.partition(".")
    return len(fraction)


def _plain(value):
    if isinstance(value, Decimal):
        return float(value)
    return value


def document_json(doc: Document) -> dict:
    invoice = doc.invoice
    return {
        "title": "COMMERCIAL INVOICE",
        "exporter": doc.exporter,
        "consignee": doc.consignee,
        "ship_to": doc.ship_to,
        "origin": doc.origin,
        "shipment_fields": [list(group) for group in SHIPMENT_FIELDS],
        "columns": [
            {"label": label, "places": _places(number_format)}
            for label, _, number_format in COLUMNS
        ],
        "lines": [
            [_plain(value) for value in line.row(serial)]
            for serial, line in enumerate(invoice.ordered(), start=1)
        ],
        "total": {
            "quantity": invoice.total_quantity,
            "net_weight_kg": _plain(invoice.total_net_weight_kg),
            "amount_usd": _plain(invoice.total_amount_usd)
            if invoice.is_priced
            else None,
        },
        "is_priced": invoice.is_priced,
        "amount_in_words": amount_in_words(invoice.total_amount_usd)
        if invoice.is_priced
        else "",
        "origin_line": ORIGIN_LINE,
        "note": IGST_NOTE,
        "declaration": DECLARATION,
        "signatory": SIGNATORY,
        "for_exporter": f"for {doc.exporter[0]}",
    }
