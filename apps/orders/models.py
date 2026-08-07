"""
Orders and packing.

An Order is what the merchant asked for. Cartons are what actually ships.
The app's whole job is converting the first into the second and proving
they match.
"""

from datetime import date

from django.db import models
from django.db.models import Max

from apps.common.calc import cbm
from apps.common.models import TimeStampedModel


class OrderStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PACKING = "packing", "Packing"
    PACKED = "packed", "Packed"
    SHIPPED = "shipped", "Shipped"


#: The status ladder. Each status can only advance to the one that follows.
NEXT_STATUS = {
    OrderStatus.DRAFT: OrderStatus.PACKING,
    OrderStatus.PACKING: OrderStatus.PACKED,
    OrderStatus.PACKED: OrderStatus.SHIPPED,
}


class Order(TimeStampedModel):
    """A merchant's purchase to fulfil."""

    number = models.CharField(
        max_length=32, unique=True, help_text="e.g. HG-2026-0142", editable=False
    )
    name = models.CharField(max_length=180, help_text="e.g. UO Fall Dining Refresh")

    merchant = models.ForeignKey(
        "masters.Merchant", on_delete=models.PROTECT, related_name="orders"
    )
    buyer_name = models.CharField(max_length=120, blank=True)

    # Shipping address, stored flat so it can be queried and validated.
    # The API nests it as a `shipping_address` object.
    ship_country = models.CharField(max_length=2, default="US")
    ship_line1 = models.CharField(max_length=180, blank=True)
    ship_line2 = models.CharField(max_length=180, blank=True)
    ship_city = models.CharField(max_length=80, blank=True)
    ship_state = models.CharField(max_length=80, blank=True)
    ship_postal_code = models.CharField(max_length=20, blank=True)

    status = models.CharField(
        max_length=10, choices=OrderStatus.choices, default=OrderStatus.DRAFT
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.number} · {self.name}"

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = self.generate_number()
        super().save(*args, **kwargs)

    @staticmethod
    def generate_number(prefix: str = "HG") -> str:
        """
        Next number in this year's sequence: HG-2026-0001, HG-2026-0002...
        The counter restarts each January.
        """
        year = date.today().year
        stem = f"{prefix}-{year}-"
        highest = (
            Order.objects.filter(number__startswith=stem).aggregate(Max("number"))[
                "number__max"
            ]
            or ""
        )
        try:
            sequence = int(highest.rsplit("-", 1)[1]) + 1
        except (IndexError, ValueError):
            sequence = 1
        return f"{stem}{sequence:04d}"

    @property
    def next_status(self):
        return NEXT_STATUS.get(OrderStatus(self.status))

    @property
    def total_ordered_quantity(self) -> int:
        return sum(line.quantity for line in self.lines.all())

    @property
    def carton_count(self) -> int:
        return self.cartons.count()


class OrderLine(models.Model):
    """
    What the merchant asked for: this product, this many.
    Purely commercial — it says nothing about boxes.
    """

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.PROTECT, related_name="order_lines"
    )
    quantity = models.PositiveIntegerField()

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "product"], name="one_line_per_product_per_order"
            )
        ]

    def __str__(self):
        return f"{self.product.style_no} × {self.quantity}"


class Carton(models.Model):
    """
    One physical shipping box, belonging to one order.

    Where a Box Type is a specification, this is the real taped-up box with
    a number on the side. Its dimensions start from the chosen box type and
    are then editable, because the box actually used is not always the box
    that was planned.
    """

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="cartons")
    carton_no = models.CharField(max_length=32, help_text="e.g. CTN-001")

    box_type = models.ForeignKey(
        "masters.BoxType", on_delete=models.SET_NULL, null=True, blank=True
    )
    length_in = models.DecimalField(
        "length (in)", max_digits=8, decimal_places=2, null=True, blank=True
    )
    width_in = models.DecimalField(
        "width (in)", max_digits=8, decimal_places=2, null=True, blank=True
    )
    height_in = models.DecimalField(
        "height (in)", max_digits=8, decimal_places=2, null=True, blank=True
    )

    gross_weight_kg = models.DecimalField(
        "gross weight (kg)",
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="The whole sealed carton, as a courier would weigh it.",
    )

    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [
            # The "duplicate carton number" blocker, enforced by the database
            # so it can never slip through however the row was created.
            models.UniqueConstraint(
                fields=["order", "carton_no"], name="unique_carton_no_per_order"
            )
        ]

    def __str__(self):
        return f"{self.order.number} / {self.carton_no}"

    @property
    def cbm(self):
        return cbm(self.length_in, self.width_in, self.height_in)

    @property
    def net_weight_kg(self):
        """Sum of everything inside this carton."""
        return sum(
            (item.net_weight_kg or 0 for item in self.contents.all()),
            start=0,
        )

    @property
    def total_quantity(self) -> int:
        return sum(item.quantity for item in self.contents.all())


class CartonUnit(models.TextChoices):
    PIECES = "pcs", "pcs"
    SET = "set", "set"


class CartonContent(models.Model):
    """
    What is inside a carton.

    This is a separate table rather than columns on Carton because a carton
    can hold more than one thing. Hardgoods rarely needs that — one product
    or one part per box — but Display packs several products into a single
    carton from a template, and retrofitting this split later would mean
    rebuilding the packing screen.

    `part` is set when this row is one part of a multi-part product. That is
    what makes reconciliation exact: a table is fully packed when every one
    of its parts has a carton, not when some quantity happens to add up.
    """

    carton = models.ForeignKey(Carton, on_delete=models.CASCADE, related_name="contents")
    product = models.ForeignKey(
        "catalog.Product", on_delete=models.PROTECT, related_name="carton_contents"
    )
    part = models.ForeignKey(
        "catalog.ProductPart",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="carton_contents",
    )

    description = models.CharField(max_length=255, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    unit = models.CharField(
        max_length=8, choices=CartonUnit.choices, default=CartonUnit.PIECES
    )

    net_weight_kg = models.DecimalField(
        "net weight (kg)", max_digits=10, decimal_places=3, null=True, blank=True
    )

    class Meta:
        ordering = ["id"]

    def __str__(self):
        label = self.product.style_no
        if self.part_id:
            label = f"{label} — {self.part.name}"
        return f"{label} × {self.quantity}"
