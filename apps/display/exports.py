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

from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Font

from apps.common import packing_sheet as sheet_kit

from .models import DisplayOrder


# The carton count goes: "CTN-001 – CTN-012" already says twelve, and the
# store arrives instead. A row lifted out of its block — sorted, filtered,
# pasted into a mail — still has to say where it is going, which the banner
# above it cannot do.
_DROPPED = "Cartons"
_KEPT = [
    index
    for index, (label, _, _) in enumerate(sheet_kit.COLUMNS)
    if label != _DROPPED
]

LAYOUT = sheet_kit.Layout(
    columns=[("Store", 12, None)] + [sheet_kit.COLUMNS[index] for index in _KEPT],
    totalled=sheet_kit.TOTALLED - {_DROPPED},
)


def packing_list_filename(order: DisplayOrder) -> str:
    return f"packing-list-{order.number}.xlsx"


def _for_store(values: list, store_name: str) -> list:
    """A canonical row from the shared kit, in this sheet's column order."""
    return [store_name] + [values[index] for index in _KEPT]


def build_packing_list(order: DisplayOrder) -> BytesIO:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = order.number

    sheet_kit.set_widths(sheet, LAYOUT)

    row = _write_heading(sheet, order)
    header_row = row + 1
    sheet_kit.write_column_headers(sheet, header_row, LAYOUT)

    row = header_row + 1
    first_data_row = row
    # Where each store's rows sit, so the grand total can skip the subtotals
    # sitting between them instead of counting every carton twice.
    spans: list[tuple[int, int]] = []

    # Colour belongs to the line, so it is per store as well as per product.
    colors = {
        (line.store_id, line.product_id): line.color for line in order.lines.all()
    }

    cartons = list(
        order.cartons.select_related("store").prefetch_related(
            "contents__product", "contents__part"
        )
    )
    by_store: dict[int, list] = {}
    for carton in cartons:
        by_store.setdefault(carton.store_id, []).append(carton)

    for store in _stores_in_order(order, by_store):
        block = by_store.get(store.id, [])
        if not block:
            continue

        sheet_kit.write_banner(sheet, row, _store_label(store), LAYOUT)
        row += 1
        block_start = row

        for group in sheet_kit.group_cartons(block):
            for values in group.rows(
                lambda content, carton: colors.get(
                    (carton.store_id, content.product_id), ""
                )
            ):
                sheet_kit.write_row(sheet, row, _for_store(values, store.name), LAYOUT)
                row += 1

        spans.append((block_start, row - 1))
        sheet_kit.write_totals(
            sheet,
            row,
            [(block_start, row - 1)],
            f"{store.name} subtotal · {len(block)} carton"
            f"{'s' if len(block) != 1 else ''}",
            LAYOUT,
        )
        row += 2

    count = len(cartons)
    sheet_kit.write_totals(
        sheet,
        row,
        spans,
        f"ORDER TOTAL · {count} carton{'s' if count != 1 else ''}",
        LAYOUT,
    )
    sheet.freeze_panes = sheet.cell(row=first_data_row, column=1)

    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


def _stores_in_order(order: DisplayOrder, by_store: dict) -> list:
    """Stores that actually have cartons, in the order the lines name them."""
    seen, stores = set(), []
    for line in order.lines.select_related("store"):
        if line.store_id in seen or line.store_id not in by_store:
            continue
        seen.add(line.store_id)
        stores.append(line.store)
    return stores


def _write_heading(sheet, order: DisplayOrder) -> int:
    title = sheet.cell(row=1, column=1, value="PACKING LIST")
    title.font = Font(bold=True, size=15)

    stores = {line.store_id for line in order.lines.all()}
    return sheet_kit.write_facts(
        sheet,
        2,
        [
            ("Order", order.number),
            ("Name", order.name),
            ("Merchant", order.merchant.name),
            ("Buyer", order.buyer_name),
            ("Stores", f"{len(stores)}"),
            ("Status", order.get_status_display()),
        ],
    )


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
