"""
The packing engine.

Three jobs, kept out of the views so they can be read, tested and reused:

    build_packing_plan   order lines  -> a proposed set of cartons
    reconcile            cartons      -> ordered vs packed, per product
    find_blockers        cartons      -> reasons the plan cannot be saved

Nothing here writes to the database except `apply_packing_plan`.
"""

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction

from apps.common import calc

from .models import Carton, CartonContent, CartonUnit, Order


# ── Auto-pack ────────────────────────────────────────────────────────


@dataclass
class PlannedContent:
    product_id: int
    part_id: int | None
    description: str
    quantity: int
    unit: str
    net_weight_kg: Decimal


@dataclass
class PlannedCarton:
    carton_no: str
    box_type_id: int | None
    length_in: Decimal | None
    width_in: Decimal | None
    height_in: Decimal | None
    gross_weight_kg: Decimal
    sort_order: int
    contents: list[PlannedContent] = field(default_factory=list)


def build_packing_plan(order: Order) -> list[PlannedCarton]:
    """
    Read each ordered product's packing recipe and propose the cartons.

    MULTI-PART product
        Every ordered unit produces one carton per part. Three tables with
        two parts each = six cartons.

    SINGLE-BOX product
        The ordered quantity is split by pack_per_box. Six chairs that pack
        two per box = three cartons, the last one possibly part-full.

    The result is a proposal, not a decision — the user edits every value
    afterwards to match what actually happened on the packing floor.
    """
    planned: list[PlannedCarton] = []
    sequence = 1

    lines = order.lines.select_related("product").prefetch_related(
        "product__parts__box_type"
    )

    for line in lines:
        product = line.product

        if product.is_multi_part:
            parts = list(product.parts.all())
            for _unit in range(line.quantity):
                for part in parts:
                    planned.append(
                        PlannedCarton(
                            carton_no=_carton_no(sequence),
                            box_type_id=part.box_type_id,
                            length_in=part.box_length_in,
                            width_in=part.box_width_in,
                            height_in=part.box_height_in,
                            gross_weight_kg=part.gross_weight_kg,
                            sort_order=sequence,
                            contents=[
                                PlannedContent(
                                    product_id=product.id,
                                    part_id=part.id,
                                    description=f"{product.description} — {part.name}",
                                    quantity=1,
                                    unit=CartonUnit.PIECES,
                                    net_weight_kg=part.net_weight_kg,
                                )
                            ],
                        )
                    )
                    sequence += 1
        else:
            per_box = product.pack_per_box or 1
            remaining = line.quantity
            while remaining > 0:
                in_this_box = min(per_box, remaining)
                remaining -= in_this_box

                planned.append(
                    PlannedCarton(
                        carton_no=_carton_no(sequence),
                        box_type_id=product.box_type_id,
                        length_in=product.box_length_in,
                        width_in=product.box_width_in,
                        height_in=product.box_height_in,
                        gross_weight_kg=calc.carton_gross_weight(
                            product.product_weight_kg,
                            product.packing_material_weight_kg,
                            product.box_weight_kg,
                            in_this_box,
                        ),
                        sort_order=sequence,
                        contents=[
                            PlannedContent(
                                product_id=product.id,
                                part_id=None,
                                description=product.description,
                                quantity=in_this_box,
                                unit=CartonUnit.PIECES,
                                net_weight_kg=calc.carton_net_weight(
                                    product.product_weight_kg,
                                    product.packing_material_weight_kg,
                                    in_this_box,
                                ),
                            )
                        ],
                    )
                )
                sequence += 1

    return planned


def _carton_no(sequence: int) -> str:
    return f"CTN-{sequence:03d}"


@transaction.atomic
def apply_packing_plan(order: Order, planned: list[PlannedCarton]) -> None:
    """Replace the order's cartons with a freshly built plan."""
    order.cartons.all().delete()
    for item in planned:
        carton = Carton.objects.create(
            order=order,
            carton_no=item.carton_no,
            box_type_id=item.box_type_id,
            length_in=item.length_in,
            width_in=item.width_in,
            height_in=item.height_in,
            gross_weight_kg=item.gross_weight_kg,
            sort_order=item.sort_order,
        )
        CartonContent.objects.bulk_create(
            [
                CartonContent(
                    carton=carton,
                    product_id=content.product_id,
                    part_id=content.part_id,
                    description=content.description,
                    quantity=content.quantity,
                    unit=content.unit,
                    net_weight_kg=content.net_weight_kg,
                )
                for content in item.contents
            ]
        )


# ── Reconciliation ───────────────────────────────────────────────────


@dataclass
class ReconciliationRow:
    product: int
    style_no: str
    ordered: int
    packed: int
    is_matched: bool


def reconcile(order: Order) -> list[ReconciliationRow]:
    """
    Ordered versus actually packed, per product. This is the check that
    stops five chairs shipping against an order for six.

    For a multi-part product a unit only counts as packed once *every* one
    of its parts has a carton. So we count each part separately and take
    the lowest — a table with three tops boxed but only two leg sets is two
    complete tables, not two and a half.
    """
    rows: list[ReconciliationRow] = []

    contents = CartonContent.objects.filter(carton__order=order).values_list(
        "product_id", "part_id", "quantity"
    )

    packed_whole: Counter[int] = Counter()
    packed_by_part: dict[int, Counter[int]] = {}

    for product_id, part_id, quantity in contents:
        if part_id is None:
            packed_whole[product_id] += quantity
        else:
            packed_by_part.setdefault(product_id, Counter())[part_id] += quantity

    for line in order.lines.select_related("product").prefetch_related("product__parts"):
        product = line.product

        if product.is_multi_part:
            part_ids = [part.id for part in product.parts.all()]
            counts = packed_by_part.get(product.id, Counter())
            packed = min((counts.get(pid, 0) for pid in part_ids), default=0)
        else:
            packed = packed_whole.get(product.id, 0)

        rows.append(
            ReconciliationRow(
                product=product.id,
                style_no=product.style_no,
                ordered=line.quantity,
                packed=packed,
                is_matched=packed == line.quantity,
            )
        )

    return rows


# ── Blockers ─────────────────────────────────────────────────────────


@dataclass
class Blocker:
    code: str
    message: str
    carton_id: int | None = None


def find_blockers(order: Order) -> list[Blocker]:
    """
    Every reason this packing plan cannot be saved.

    An empty list means the plan is sound. Anything in it is shown in the
    footer of the packing screen and disables the save button.
    """
    blockers: list[Blocker] = []
    cartons = list(
        order.cartons.prefetch_related("contents").select_related("box_type")
    )

    numbers = Counter(
        (carton.carton_no or "").strip() for carton in cartons if carton.carton_no
    )

    for index, carton in enumerate(cartons, start=1):
        label = (carton.carton_no or "").strip() or f"row {index}"

        if not (carton.carton_no or "").strip():
            blockers.append(
                Blocker(
                    code="missing_carton_no",
                    message=f"Row {index} is missing a carton number",
                    carton_id=carton.id,
                )
            )

        if not carton.box_type_id:
            blockers.append(
                Blocker(
                    code="missing_box_type",
                    message=f"Carton {label} has no box type",
                    carton_id=carton.id,
                )
            )

        gross = carton.gross_weight_kg or Decimal("0")
        net = carton.net_weight_kg or Decimal("0")
        if gross < net:
            blockers.append(
                Blocker(
                    code="gross_below_net",
                    message=(
                        f"Carton {label}: gross weight {gross} kg is below "
                        f"net weight {net} kg"
                    ),
                    carton_id=carton.id,
                )
            )

    for number, count in numbers.items():
        if count > 1:
            blockers.append(
                Blocker(
                    code="duplicate_carton_no",
                    message=f"Carton number “{number}” is used {count} times",
                )
            )

    for row in reconcile(order):
        if not row.is_matched:
            blockers.append(
                Blocker(
                    code="quantity_mismatch",
                    message=(
                        f"{row.style_no}: packed {row.packed} of {row.ordered} ordered"
                    ),
                )
            )

    return blockers


# ── Plan summary ─────────────────────────────────────────────────────


def packing_summary(order: Order) -> dict:
    """Everything the packing screen's footer and chips need, in one call."""
    cartons = list(order.cartons.prefetch_related("contents"))
    blockers = find_blockers(order)

    return {
        "reconciliation": reconcile(order),
        "blockers": blockers,
        "carton_count": len(cartons),
        "total_quantity": sum(carton.total_quantity for carton in cartons),
        "total_gross_weight_kg": sum(
            (carton.gross_weight_kg or Decimal("0") for carton in cartons),
            start=Decimal("0"),
        ),
        "total_cbm": sum(
            (carton.cbm for carton in cartons), start=Decimal("0")
        ),
        "can_save": not blockers and bool(cartons),
    }
