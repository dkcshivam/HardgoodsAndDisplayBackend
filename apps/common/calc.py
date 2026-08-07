"""
The domain maths, in one place. This module is the source of truth —
`frontend/src/lib/calc.ts` mirrors it so forms can show live answers,
but every stored value comes from here.

UNITS, decided once and never mixed:
    dimensions -> inches (in)
    weights    -> kilograms (kg)
    volume     -> cubic metres (CBM)

Decimal is used throughout rather than float. 0.1 + 0.2 is exactly 0.3
in Decimal; in float it is 0.30000000000000004, which is not something
you want on a customs declaration.
"""

from decimal import Decimal

# 1 cubic metre = 61,023.744 cubic inches.
CUBIC_INCHES_PER_CBM = Decimal("61023.744094732284")

CBM_PLACES = Decimal("0.0001")
WEIGHT_PLACES = Decimal("0.001")

ZERO = Decimal("0")


def _d(value) -> Decimal:
    """Coerce None or a number to Decimal, treating None as zero."""
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def cbm(length_in, width_in, height_in) -> Decimal:
    """
    Cubic metres from box dimensions in inches.
    Any missing dimension makes the volume meaningless, so we return zero.
    """
    length, width, height = _d(length_in), _d(width_in), _d(height_in)
    if not (length and width and height):
        return ZERO.quantize(CBM_PLACES)
    return (length * width * height / CUBIC_INCHES_PER_CBM).quantize(CBM_PLACES)


def net_weight(product_weight_kg, packing_material_weight_kg) -> Decimal:
    """
    Everything inside the box: the item itself plus its padding.
    Excludes the carton.
    """
    total = _d(product_weight_kg) + _d(packing_material_weight_kg)
    return total.quantize(WEIGHT_PLACES)


def gross_weight(product_weight_kg, packing_material_weight_kg, box_weight_kg) -> Decimal:
    """
    The whole sealed carton — what a courier would put on the scale.
    Net plus the empty carton itself.
    """
    total = net_weight(product_weight_kg, packing_material_weight_kg) + _d(box_weight_kg)
    return total.quantize(WEIGHT_PLACES)


def carton_net_weight(product_weight_kg, packing_material_weight_kg, quantity: int):
    """
    Net weight of one carton holding `quantity` units.

    Product weight is per unit; packing material is per carton. A box of two
    chairs holds two chair-weights but only one lot of padding.
    """
    total = _d(product_weight_kg) * quantity + _d(packing_material_weight_kg)
    return total.quantize(WEIGHT_PLACES)


def carton_gross_weight(
    product_weight_kg, packing_material_weight_kg, box_weight_kg, quantity: int
):
    """Gross weight of one carton holding `quantity` units."""
    total = (
        carton_net_weight(product_weight_kg, packing_material_weight_kg, quantity)
        + _d(box_weight_kg)
    )
    return total.quantize(WEIGHT_PLACES)


def carton_count(quantity: int, pack_per_box: int) -> int:
    """
    How many cartons a quantity of a single-box product needs.
    6 chairs that pack 2-per-box = 3 cartons.
    """
    if pack_per_box <= 0:
        return 0
    return -(-quantity // pack_per_box)  # ceiling division
