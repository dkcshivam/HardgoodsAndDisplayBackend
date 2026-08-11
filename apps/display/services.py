"""
The step engine. A template is applied as many times as the order's remaining
quantities allow; what is left over is what the next template gets authored
against. Nothing here writes except `apply_step`, `recount_step` and
`delete_step`.
"""

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction
from django.db.models import Max, Q

from apps.common import calc

from .models import (
    CartonUnit,
    DisplayCarton,
    DisplayCartonContent,
    DisplayOrder,
    PackStep,
    PackTemplate,
)

# Below this share of the box actually occupied, the carton is mostly air and
# the shipping line is billing for volume that carries nothing.
FILL_WARNING_RATIO = Decimal("0.30")


class PackingError(Exception):
    """A step that cannot be applied. Carries a message fit for the screen."""


# ── Demand ───────────────────────────────────────────────────────────

#: What the loop counts: a whole product, or one part of one.
Piece = tuple[int, int | None]


def _lines(order: DisplayOrder):
    return order.lines.select_related("product").prefetch_related("product__parts")


def ordered_quantities(order: DisplayOrder) -> Counter:
    """
    Demand, counted in pieces.

    A multi-part product is ordered whole but packed part by part, so ten
    tables is a demand for ten tops *and* ten legs — each has to find a box,
    and they need not find the same one.
    """
    demand: Counter = Counter()
    for line in _lines(order):
        product = line.product
        if product.is_multi_part:
            for part in product.parts.all():
                demand[(product.id, part.id)] += line.quantity
        else:
            demand[(product.id, None)] += line.quantity
    return demand


def packed_quantities(order: DisplayOrder) -> Counter:
    packed: Counter = Counter()
    rows = DisplayCartonContent.objects.filter(carton__order=order).values_list(
        "product_id", "part_id", "quantity"
    )
    for product_id, part_id, quantity in rows:
        packed[(product_id, part_id)] += quantity
    return packed


def remaining_quantities(order: DisplayOrder) -> dict[Piece, int]:
    """
    What still needs a box.

    Counted from the cartons that exist rather than from the steps, so a
    hand-edited carton moves the number too — the boxes are the truth.
    """
    packed = packed_quantities(order)
    remaining = {}
    for piece, quantity in ordered_quantities(order).items():
        short = quantity - packed.get(piece, 0)
        if short > 0:
            remaining[piece] = short
    return remaining


def max_applications(template: PackTemplate, remaining: dict[Piece, int]) -> int:
    """
    How many times this template fits what is left: the smallest whole number
    of boxes any one of its pieces allows.

    12 ornament sets + 6 garlands against 96 and 158 gives
    min(96//12, 158//6) = min(8, 26) = 8 — capped by the ornaments.
    """
    items = list(template.items.all())
    if not items:
        return 0
    return min(
        remaining.get((item.product_id, item.part_id), 0) // item.quantity
        for item in items
    )


# ── Applying a step ──────────────────────────────────────────────────


@transaction.atomic
def apply_step(
    order: DisplayOrder, template: PackTemplate, count: int | None = None
) -> PackStep:
    """
    Add one step to the plan and build its cartons. `count` defaults to the
    most that will fit, which is the common case and makes the loop one click.
    """
    capacity = max_applications(template, remaining_quantities(order))

    if capacity < 1:
        raise PackingError(
            f"{template.code} does not fit what is left of this order."
        )

    if count is None:
        count = capacity
    if count < 1:
        raise PackingError("A step must apply its template at least once.")
    if count > capacity:
        raise PackingError(
            f"{template.code} fits {capacity} more time(s), not {count}."
        )

    sequence = (order.steps.aggregate(Max("sequence"))["sequence__max"] or 0) + 1
    step = PackStep.objects.create(
        order=order, sequence=sequence, template=template, count=count
    )
    _build_cartons(step)
    return step


def _build_cartons(step: PackStep) -> None:
    """Materialise this step's boxes, numbering on from the order's highest."""
    order = step.order
    template = step.template
    items = list(template.items.select_related("product", "part"))

    weights = [(item.piece.product_weight_kg, item.quantity) for item in items]
    gross = calc.mixed_carton_gross_weight(
        weights, template.packing_material_weight_kg, template.box_weight_kg
    )

    start = (order.cartons.aggregate(Max("sort_order"))["sort_order__max"] or 0) + 1

    cartons = [
        DisplayCarton(
            order=order,
            step=step,
            carton_no=f"CTN-{start + offset:03d}",
            length_in=template.box_length_in,
            width_in=template.box_width_in,
            height_in=template.box_height_in,
            box_weight_kg=template.box_weight_kg,
            packing_material_weight_kg=template.packing_material_weight_kg,
            gross_weight_kg=gross,
            sort_order=start + offset,
        )
        for offset in range(step.count)
    ]
    DisplayCarton.objects.bulk_create(cartons)

    contents = [
        DisplayCartonContent(
            carton=carton,
            product=item.product,
            part=item.part,
            description=_describe(item),
            quantity=item.quantity,
            unit=CartonUnit.PIECES,
            net_weight_kg=calc.mixed_carton_net_weight(
                [(item.piece.product_weight_kg, item.quantity)], None
            ),
        )
        for carton in cartons
        for item in items
    ]
    DisplayCartonContent.objects.bulk_create(contents)


# ── Editing the plan ─────────────────────────────────────────────────


@dataclass
class Adjustment:
    """A step the replay had to change, because an earlier one moved."""

    sequence: int
    template_code: str
    was: int
    now: int


@transaction.atomic
def recount_step(order: DisplayOrder, sequence: int, count: int) -> list[Adjustment]:
    step = _step(order, sequence)
    if count < 1:
        raise PackingError("A step must apply its template at least once.")
    step.count = count
    step.save(update_fields=["count"])
    return _replay_from(order, sequence)


@transaction.atomic
def delete_step(order: DisplayOrder, sequence: int) -> list[Adjustment]:
    step = _step(order, sequence)
    step.cartons.all().delete()
    step.delete()
    return _replay_from(order, sequence)


def _step(order: DisplayOrder, sequence: int) -> PackStep:
    step = order.steps.filter(sequence=sequence).first()
    if step is None:
        raise PackingError(f"This order has no step {sequence}.")
    return step


def _replay_from(order: DisplayOrder, sequence: int) -> list[Adjustment]:
    """
    Rebuild every step from `sequence` on.

    Counts are kept but clamped to what the order can still supply: lowering
    an early step can leave a later one with more to pack, and raising it can
    leave a later one with nothing. A step clamped to nothing is dropped, and
    reported rather than silently vanishing.

    Cartons before `sequence` keep their numbers — a number already written on
    a physical box must not move because a later step changed.
    """
    DisplayCarton.objects.filter(order=order, step__sequence__gte=sequence).delete()

    adjustments: list[Adjustment] = []

    for step in list(order.steps.filter(sequence__gte=sequence).order_by("sequence")):
        capacity = max_applications(step.template, remaining_quantities(order))

        if capacity < 1:
            adjustments.append(
                Adjustment(step.sequence, step.template.code, step.count, 0)
            )
            step.delete()
            continue

        if step.count > capacity:
            adjustments.append(
                Adjustment(step.sequence, step.template.code, step.count, capacity)
            )
            step.count = capacity
            step.save(update_fields=["count"])

        _build_cartons(step)

    _resequence(order)
    return adjustments


def _resequence(order: DisplayOrder) -> None:
    """Close gaps left by a deleted step so the plan reads 1, 2, 3."""
    steps = list(order.steps.order_by("sequence", "id"))
    if [step.sequence for step in steps] == list(range(1, len(steps) + 1)):
        return

    # Park them above every number in use before renumbering down: a straight
    # pass would collide with the unique constraint, and the column is
    # positive-only so negatives are not available as scratch space.
    scratch = max(step.sequence for step in steps) + 1
    for index, step in enumerate(steps):
        PackStep.objects.filter(pk=step.pk).update(sequence=scratch + index)
    for index, step in enumerate(steps, start=1):
        PackStep.objects.filter(pk=step.pk).update(sequence=index)


# ── The trace ────────────────────────────────────────────────────────


@dataclass
class StepRow:
    sequence: int
    template: int
    template_code: str
    template_name: str
    count: int
    carton_count: int
    consumed: list[dict] = field(default_factory=list)
    remaining_after: list[dict] = field(default_factory=list)


def step_rows(order: DisplayOrder) -> list[StepRow]:
    """
    The plan as the screen shows it — what each step consumed and what was
    left afterwards. This is the derivation, and it is why a packer will trust
    the number 36 rather than redo it by hand.
    """
    pieces = _piece_index(order)
    running = dict(ordered_quantities(order))
    rows: list[StepRow] = []

    steps = order.steps.select_related("template").prefetch_related(
        "template__items__product", "template__items__part"
    )

    for step in steps:
        consumed = []
        for item in step.template.items.all():
            piece = (item.product_id, item.part_id)
            used = item.quantity * step.count
            running[piece] = running.get(piece, 0) - used
            consumed.append(_quantity_row(piece, used, pieces))

        rows.append(
            StepRow(
                sequence=step.sequence,
                template=step.template_id,
                template_code=step.template.code,
                template_name=step.template.name,
                count=step.count,
                carton_count=step.count,
                consumed=consumed,
                remaining_after=[
                    _quantity_row(piece, qty, pieces)
                    for piece, qty in running.items()
                    if qty > 0
                ],
            )
        )

    return rows


def remaining_rows(order: DisplayOrder) -> list[dict]:
    pieces = _piece_index(order)
    return [
        _quantity_row(piece, qty, pieces)
        for piece, qty in remaining_quantities(order).items()
    ]


def _piece_index(order: DisplayOrder) -> dict[Piece, tuple]:
    """Every piece this order asks for, so a row can name what it counts."""
    index: dict[Piece, tuple] = {}
    for line in _lines(order):
        product = line.product
        if product.is_multi_part:
            for part in product.parts.all():
                index[(product.id, part.id)] = (product, part)
        else:
            index[(product.id, None)] = (product, None)
    return index


def _quantity_row(piece: Piece, quantity: int, pieces: dict) -> dict:
    product_id, part_id = piece
    product, part = pieces.get(piece, (None, None))
    return {
        "product": product_id,
        "part": part_id,
        "style_no": product.style_no if product else "",
        "part_name": part.name if part else "",
        "description": _piece_description(product, part),
        "quantity": quantity,
    }


def _piece_description(product, part) -> str:
    if product is None:
        return ""
    if part is None:
        return product.description
    return f"{product.description} — {part.name}"


def _describe(item) -> str:
    return _piece_description(item.product, item.part)


# ── Which templates are worth offering ───────────────────────────────


def applicable_templates(order: DisplayOrder) -> list[dict]:
    """
    The picker: designs that fit what is left, biggest first. A template that
    fits zero times is not offered, because applying it is the one thing the
    loop can never do.

    Three ways in: a global library design, a library design for this
    merchant, or a one-off written for this order.
    """
    remaining = remaining_quantities(order)
    if not remaining:
        return []

    templates = (
        PackTemplate.objects.filter(is_active=True)
        .filter(
            Q(is_library=True, merchant__isnull=True)
            | Q(is_library=True, merchant=order.merchant_id)
            | Q(order=order)
        )
        .prefetch_related("items__product")
        .distinct()
    )

    rows = []
    for template in templates:
        capacity = max_applications(template, remaining)
        if capacity < 1:
            continue
        rows.append(
            {
                "template": template.id,
                "code": template.code,
                "name": template.name,
                "capacity": capacity,
                "units_per_carton": template.total_units,
            }
        )

    rows.sort(key=lambda row: row["capacity"] * row["units_per_carton"], reverse=True)
    return rows


# ── Reconciliation ───────────────────────────────────────────────────


@dataclass
class ReconciliationRow:
    product: int
    style_no: str
    ordered: int
    packed: int
    is_matched: bool


def reconcile(order: DisplayOrder) -> list[ReconciliationRow]:
    """
    Ordered against actually boxed.

    A multi-part product counts as packed only once every part has a box, so
    each part is counted on its own and the lowest wins: twenty tops and
    eighteen legs is eighteen tables, not nineteen. That is both true and
    actionable — go and find two legs.
    """
    packed = packed_quantities(order)
    rows = []

    for line in _lines(order):
        product = line.product

        if product.is_multi_part:
            counts = [
                packed.get((product.id, part.id), 0) for part in product.parts.all()
            ]
            boxed = min(counts, default=0)
        else:
            boxed = packed.get((product.id, None), 0)

        rows.append(
            ReconciliationRow(
                product=product.id,
                style_no=product.style_no,
                ordered=line.quantity,
                packed=boxed,
                is_matched=boxed == line.quantity,
            )
        )

    return rows


# ── Blockers and warnings ────────────────────────────────────────────


@dataclass
class Blocker:
    code: str
    message: str
    carton_id: int | None = None


@dataclass
class Warning_:
    code: str
    message: str
    carton_id: int | None = None


def find_blockers(order: DisplayOrder) -> list[Blocker]:
    """Every reason this plan cannot be saved. Empty means it is sound."""
    blockers: list[Blocker] = []
    cartons = list(order.cartons.prefetch_related("contents"))

    numbers = Counter(
        (carton.carton_no or "").strip() for carton in cartons if carton.carton_no
    )

    for index, carton in enumerate(cartons, start=1):
        label = (carton.carton_no or "").strip() or f"row {index}"

        if not (carton.carton_no or "").strip():
            blockers.append(
                Blocker(
                    "missing_carton_no",
                    f"Row {index} is missing a carton number",
                    carton.id,
                )
            )

        missing = [
            name
            for name, value in (
                ("length", carton.length_in),
                ("width", carton.width_in),
                ("height", carton.height_in),
            )
            if not value
        ]
        if missing:
            named = (
                missing[0]
                if len(missing) == 1
                else f"{', '.join(missing[:-1])} and {missing[-1]}"
            )
            blockers.append(
                Blocker(
                    "missing_dimensions",
                    f"Carton {label} is missing its {named}",
                    carton.id,
                )
            )

        gross = carton.gross_weight_kg or Decimal("0")
        net = carton.net_weight_kg or Decimal("0")
        if gross < net:
            blockers.append(
                Blocker(
                    "gross_below_net",
                    f"Carton {label}: gross weight {gross} kg is below "
                    f"net weight {net} kg",
                    carton.id,
                )
            )

    for number, count in numbers.items():
        if count > 1:
            blockers.append(
                Blocker(
                    "duplicate_carton_no",
                    f"Carton number “{number}” is used {count} times",
                )
            )

    for row in reconcile(order):
        if not row.is_matched:
            blockers.append(
                Blocker(
                    "quantity_mismatch",
                    f"{row.style_no}: packed {row.packed} of {row.ordered} ordered",
                )
            )

    return blockers


def find_warnings(order: DisplayOrder) -> list[Warning_]:
    """
    Advisory only. A template records a box somebody physically packed, so the
    app flags its own arithmetic and never overrules the human.
    """
    warnings: list[Warning_] = []

    cartons = order.cartons.select_related("step__template").prefetch_related(
        "contents__product", "contents__part", "step__template__items"
    )

    for carton in cartons:
        label = (carton.carton_no or "").strip() or str(carton.id)

        if carton.step_id:
            allowed = {
                (item.product_id, item.part_id): item.quantity
                for item in carton.step.template.items.all()
            }
            for content in carton.contents.all():
                permitted = allowed.get((content.product_id, content.part_id), 0)
                if content.quantity > permitted:
                    warnings.append(
                        Warning_(
                            "template_capacity_exceeded",
                            f"Carton {label} holds {content.quantity} × "
                            f"{content.piece_label}, more than the "
                            f"{carton.step.template.code} template's {permitted}",
                            carton.id,
                        )
                    )

        box = carton.cbm
        if not box:
            continue
        occupied = sum(
            (content.piece.unit_cbm * content.quantity for content in carton.contents.all()),
            start=Decimal("0"),
        )
        if occupied and occupied / box < FILL_WARNING_RATIO:
            share = (occupied / box * 100).quantize(Decimal("1"))
            warnings.append(
                Warning_(
                    "poor_fill",
                    f"Carton {label} is only about {share}% full — "
                    f"the rest is freight paid on air",
                    carton.id,
                )
            )

    return warnings


# ── Plan summary ─────────────────────────────────────────────────────


def packing_summary(order: DisplayOrder) -> dict:
    """
    Everything the packing screen needs except the cartons themselves, which
    are paginated separately — a finished plan can run to thousands of boxes
    and the screen shows steps, not boxes.
    """
    cartons = list(order.cartons.prefetch_related("contents"))
    blockers = find_blockers(order)

    return {
        "order": order.id,
        "steps": step_rows(order),
        "remaining": remaining_rows(order),
        "applicable_templates": applicable_templates(order),
        "reconciliation": reconcile(order),
        "blockers": blockers,
        "warnings": find_warnings(order),
        "carton_count": len(cartons),
        "total_quantity": sum(carton.total_quantity for carton in cartons),
        "total_gross_weight_kg": sum(
            (carton.gross_weight_kg or Decimal("0") for carton in cartons),
            start=Decimal("0"),
        ),
        "total_cbm": sum((carton.cbm for carton in cartons), start=Decimal("0")),
        "can_save": not blockers and bool(cartons),
    }
