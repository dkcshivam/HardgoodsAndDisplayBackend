"""
Display packing. Somebody who knows how the goods really pack authors a
template — "30 bows and 5 wreaths, in this box" — and the app applies it as
many times as the order allows, then shows what is left for the next one to be
authored against.

The plan is the list of steps. Cartons are what they produce.
"""

from datetime import date

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Max

from apps.common import calc
from apps.common.models import TimeStampedModel


class DisplayProductStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"


class DisplayProduct(TimeStampedModel):
    """
    One display SKU. Unlike a Hardgoods product it owns no box — it only ever
    ships inside a pack template's carton, so the box lives there instead.
    These dimensions are for customs and fit-checking, never for packing.
    """

    style_no = models.CharField(
        max_length=64, unique=True, help_text="Unique SKU code, e.g. DSP-WRT-24"
    )
    description = models.CharField(max_length=255, help_text='e.g. 24" Pine Wreath')

    category = models.ForeignKey(
        "masters.Category",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="display_products",
    )
    customs_description = models.CharField(max_length=255, blank=True)
    hsn_code = models.CharField(max_length=20, blank=True)

    status = models.CharField(
        max_length=10,
        choices=DisplayProductStatus.choices,
        default=DisplayProductStatus.ACTIVE,
    )

    product_weight_kg = models.DecimalField(
        "product weight (kg)",
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="The bare item with no packaging.",
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

    class Meta:
        ordering = ["style_no"]

    def __str__(self):
        return f"{self.style_no} · {self.description}"

    @property
    def unit_cbm(self):
        """One item's own volume — used to warn when a box is mostly air."""
        return calc.cbm(self.length_in, self.width_in, self.height_in)


class PackTemplate(TimeStampedModel):
    """
    A box design: which display products go inside and how many of each.

    The box belongs here rather than to the products. That inversion is the
    whole structural difference from Hardgoods, where a chair knows its own
    carton.
    """

    code = models.CharField(max_length=32, unique=True, help_text="e.g. TPL-001")
    name = models.CharField(max_length=180, help_text="e.g. 30 bows + 5 wreaths")

    merchant = models.ForeignKey(
        "masters.Merchant",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="pack_templates",
        help_text="Leave empty to offer this template on every order.",
    )
    remark = models.TextField(blank=True)

    box_length_in = models.DecimalField(
        "box length (in)", max_digits=8, decimal_places=2, null=True, blank=True
    )
    box_width_in = models.DecimalField(
        "box width (in)", max_digits=8, decimal_places=2, null=True, blank=True
    )
    box_height_in = models.DecimalField(
        "box height (in)", max_digits=8, decimal_places=2, null=True, blank=True
    )
    box_weight_kg = models.DecimalField(
        "box weight (kg)",
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="The empty carton on its own.",
    )
    packing_material_weight_kg = models.DecimalField(
        "packing material weight (kg)",
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Padding and filler inside the box, not the box itself.",
    )

    # Templates are authored in-flow against one order's tail, so a one-off
    # like "2 garlands" is normal and must not silt up the next order's picker.
    is_library = models.BooleanField(
        default=False, help_text="On = offer this template on later orders too."
    )
    # Scope for a one-off: it is offered on the order it was written for, and
    # nowhere else. Without this a non-library template would be saved and then
    # never appear anywhere, which is the same as losing it.
    order = models.ForeignKey(
        "display.DisplayOrder",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="own_templates",
        help_text="Set on a one-off, so it is offered only on that order.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} · {self.name}"

    @property
    def cbm(self):
        return calc.cbm(self.box_length_in, self.box_width_in, self.box_height_in)

    @property
    def total_units(self) -> int:
        return sum(item.quantity for item in self.items.all())

    @property
    def net_weight_kg(self):
        """A full box of this template. Never stored — a part-filled one differs."""
        return calc.mixed_carton_net_weight(
            [(item.product.product_weight_kg, item.quantity) for item in self.items.all()],
            self.packing_material_weight_kg,
        )

    @property
    def gross_weight_kg(self):
        return calc.mixed_carton_gross_weight(
            [(item.product.product_weight_kg, item.quantity) for item in self.items.all()],
            self.packing_material_weight_kg,
            self.box_weight_kg,
        )


class PackTemplateItem(models.Model):
    template = models.ForeignKey(
        PackTemplate, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey(
        DisplayProduct, on_delete=models.PROTECT, related_name="template_items"
    )
    # At least one, or a template could consume nothing and apply forever.
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        ordering = ["id"]
        verbose_name = "item"
        constraints = [
            models.UniqueConstraint(
                fields=["template", "product"], name="one_row_per_product_per_template"
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1), name="template_item_quantity_positive"
            ),
        ]

    def __str__(self):
        return f"{self.product.style_no} × {self.quantity}"


class DisplayOrderStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PACKING = "packing", "Packing"
    PACKED = "packed", "Packed"
    SHIPPED = "shipped", "Shipped"


NEXT_STATUS = {
    DisplayOrderStatus.DRAFT: DisplayOrderStatus.PACKING,
    DisplayOrderStatus.PACKING: DisplayOrderStatus.PACKED,
    DisplayOrderStatus.PACKED: DisplayOrderStatus.SHIPPED,
}


class DisplayOrder(TimeStampedModel):
    number = models.CharField(
        max_length=32, unique=True, help_text="e.g. DP-2026-0142", editable=False
    )
    name = models.CharField(max_length=180, help_text="e.g. UO Winter Electronics")

    merchant = models.ForeignKey(
        "masters.Merchant", on_delete=models.PROTECT, related_name="display_orders"
    )
    buyer_name = models.CharField(max_length=120, blank=True)

    ship_country = models.CharField(max_length=2, default="US")
    ship_line1 = models.CharField(max_length=180, blank=True)
    ship_line2 = models.CharField(max_length=180, blank=True)
    ship_city = models.CharField(max_length=80, blank=True)
    ship_state = models.CharField(max_length=80, blank=True)
    ship_postal_code = models.CharField(max_length=20, blank=True)

    status = models.CharField(
        max_length=10,
        choices=DisplayOrderStatus.choices,
        default=DisplayOrderStatus.DRAFT,
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
    def generate_number(prefix: str = "DP") -> str:
        year = date.today().year
        stem = f"{prefix}-{year}-"
        highest = (
            DisplayOrder.objects.filter(number__startswith=stem).aggregate(
                Max("number")
            )["number__max"]
            or ""
        )
        try:
            sequence = int(highest.rsplit("-", 1)[1]) + 1
        except (IndexError, ValueError):
            sequence = 1
        return f"{stem}{sequence:04d}"

    @property
    def next_status(self):
        return NEXT_STATUS.get(DisplayOrderStatus(self.status))

    @property
    def total_ordered_quantity(self) -> int:
        return sum(line.quantity for line in self.lines.all())

    @property
    def carton_count(self) -> int:
        return self.cartons.count()


class DisplayOrderLine(models.Model):
    order = models.ForeignKey(
        DisplayOrder, on_delete=models.CASCADE, related_name="lines"
    )
    product = models.ForeignKey(
        DisplayProduct, on_delete=models.PROTECT, related_name="order_lines"
    )
    quantity = models.PositiveIntegerField()
    color = models.CharField(max_length=60, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "product"],
                name="one_display_line_per_product_per_order",
            )
        ]

    def __str__(self):
        return f"{self.product.style_no} × {self.quantity}"


class PackStep(models.Model):
    """
    One application of a template: "TPL-001, thirty-six times".

    Kept as a row rather than left implicit in the cartons because the loop is
    greedy: a choice made at step 1 is only revealed as wrong at step 4, and
    the fix is to change step 1 and replay.
    """

    order = models.ForeignKey(DisplayOrder, on_delete=models.CASCADE, related_name="steps")
    sequence = models.PositiveIntegerField()
    template = models.ForeignKey(
        PackTemplate, on_delete=models.PROTECT, related_name="steps"
    )
    count = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        ordering = ["sequence", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "sequence"], name="unique_step_sequence_per_order"
            ),
            models.CheckConstraint(
                condition=models.Q(count__gte=1), name="step_count_positive"
            ),
        ]

    def __str__(self):
        return f"{self.order.number} / step {self.sequence}: {self.template.code} × {self.count}"


class CartonUnit(models.TextChoices):
    PIECES = "pcs", "pcs"
    SET = "set", "set"


class DisplayCarton(models.Model):
    """
    One physical box. Seeded from its step's template and editable afterwards,
    because the box actually used is not always the box planned.
    """

    order = models.ForeignKey(
        DisplayOrder, on_delete=models.CASCADE, related_name="cartons"
    )
    carton_no = models.CharField(max_length=32, help_text="e.g. CTN-001")

    # Provenance, not constraint: contents may be edited away from the template,
    # and a null step means somebody built this box by hand.
    step = models.ForeignKey(
        PackStep,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cartons",
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

    box_weight_kg = models.DecimalField(
        "box weight (kg)", max_digits=10, decimal_places=3, null=True, blank=True
    )
    # Copied here rather than read through the step, so a hand-built carton
    # with no template still has a complete net weight.
    packing_material_weight_kg = models.DecimalField(
        "packing material weight (kg)",
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
    )
    gross_weight_kg = models.DecimalField(
        "gross weight (kg)", max_digits=10, decimal_places=3, null=True, blank=True
    )

    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "carton_no"], name="unique_display_carton_no_per_order"
            )
        ]

    def __str__(self):
        return f"{self.order.number} / {self.carton_no}"

    @property
    def cbm(self):
        return calc.cbm(self.length_in, self.width_in, self.height_in)

    @property
    def net_weight_kg(self):
        """Contents plus this carton's padding. Never stored — D1."""
        contents = sum(
            (item.net_weight_kg or 0 for item in self.contents.all()), start=0
        )
        return contents + (self.packing_material_weight_kg or 0)

    @property
    def total_quantity(self) -> int:
        return sum(item.quantity for item in self.contents.all())


class DisplayCartonContent(models.Model):
    """
    One product's presence in one box. Several rows per carton is the norm
    here, which is the point of the module.
    """

    carton = models.ForeignKey(
        DisplayCarton, on_delete=models.CASCADE, related_name="contents"
    )
    product = models.ForeignKey(
        DisplayProduct, on_delete=models.PROTECT, related_name="carton_contents"
    )

    description = models.CharField(max_length=255, blank=True)
    quantity = models.PositiveIntegerField(default=1)
    unit = models.CharField(
        max_length=8, choices=CartonUnit.choices, default=CartonUnit.PIECES
    )

    # This product's own weight only. The carton's padding sits on the carton,
    # since it belongs to the box rather than to any one thing inside it.
    net_weight_kg = models.DecimalField(
        "net weight (kg)", max_digits=10, decimal_places=3, null=True, blank=True
    )

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.product.style_no} × {self.quantity}"
