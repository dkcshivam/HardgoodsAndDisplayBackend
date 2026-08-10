"""
Source of truth for the domain maths. `frontend/src/lib/calc.ts` mirrors this
for live form feedback; every stored value comes from here.

Dimensions are inches, weights kilograms, volume cubic metres. Decimal
throughout — float rounding has no place on a customs declaration.
"""

from decimal import Decimal

CUBIC_INCHES_PER_CBM = Decimal("61023.744094732284")

CBM_PLACES = Decimal("0.0001")
WEIGHT_PLACES = Decimal("0.001")

ZERO = Decimal("0")


def _d(value) -> Decimal:
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def cbm(length_in, width_in, height_in) -> Decimal:
    length, width, height = _d(length_in), _d(width_in), _d(height_in)
    if not (length and width and height):
        return ZERO.quantize(CBM_PLACES)
    return (length * width * height / CUBIC_INCHES_PER_CBM).quantize(CBM_PLACES)


def net_weight(product_weight_kg, packing_material_weight_kg) -> Decimal:
    """Everything inside the box: the item plus its padding, not the carton."""
    total = _d(product_weight_kg) + _d(packing_material_weight_kg)
    return total.quantize(WEIGHT_PLACES)


def gross_weight(product_weight_kg, packing_material_weight_kg, box_weight_kg) -> Decimal:
    """The whole sealed carton, as a courier would weigh it."""
    total = net_weight(product_weight_kg, packing_material_weight_kg) + _d(box_weight_kg)
    return total.quantize(WEIGHT_PLACES)


def carton_net_weight(product_weight_kg, packing_material_weight_kg, quantity: int):
    """Product weight is per unit; packing material is per carton."""
    total = _d(product_weight_kg) * quantity + _d(packing_material_weight_kg)
    return total.quantize(WEIGHT_PLACES)


def carton_gross_weight(
    product_weight_kg, packing_material_weight_kg, box_weight_kg, quantity: int
):
    total = (
        carton_net_weight(product_weight_kg, packing_material_weight_kg, quantity)
        + _d(box_weight_kg)
    )
    return total.quantize(WEIGHT_PLACES)


def mixed_carton_net_weight(items, packing_material_weight_kg) -> Decimal:
    """
    A Display carton holds several different products from one pack template.
    Each contributes its unit weight times its quantity; packing material is
    per carton. `items` is (product_weight_kg, quantity) pairs.
    """
    total = sum((_d(weight) * quantity for weight, quantity in items), start=ZERO)
    return (total + _d(packing_material_weight_kg)).quantize(WEIGHT_PLACES)


def mixed_carton_gross_weight(
    items, packing_material_weight_kg, box_weight_kg
) -> Decimal:
    total = (
        mixed_carton_net_weight(items, packing_material_weight_kg)
        + _d(box_weight_kg)
    )
    return total.quantize(WEIGHT_PLACES)


def carton_count(quantity: int, pack_per_box: int) -> int:
    if pack_per_box <= 0:
        return 0
    return -(-quantity // pack_per_box)
