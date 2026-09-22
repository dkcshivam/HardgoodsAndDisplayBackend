"""
Display packing. Somebody who knows how the goods really pack authors a
template — "30 bows and 5 wreaths, in this box" — and the app applies it as
many times as the order allows, then shows what is left for the next one to be
authored against.

The plan is the list of steps. Cartons are what they produce.
"""

from datetime import date

from django.core.exceptions import ValidationError
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
    style_name = models.CharField(
        max_length=180, blank=True, help_text="The buyer's name for the style."
    )
    description = models.CharField(
        max_length=255, blank=True, help_text='e.g. 24" Pine Wreath'
    )

    category = models.ForeignKey(
        "masters.Category",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="display_products",
    )
    customs_description = models.CharField(max_length=255, blank=True)
    hsn_code = models.CharField(max_length=20, blank=True)
    # The US tariff code the invoice prints; HSN is India's, for export.
    hts_code = models.CharField(max_length=20, blank=True)

    # Fixed at creation: every template item, step and carton already written
    # against this SKU assumed one shape or the other.
    is_multi_part = models.BooleanField(
        default=False,
        help_text="On = packs as separate parts, which may go in different templates.",
    )
    status = models.CharField(
        max_length=10,
        choices=DisplayProductStatus.choices,
        default=DisplayProductStatus.ACTIVE,
    )

    # Carried on the piece for the desk's own use. Nothing in packing, the
    # packing list or the invoice reads it yet — say the word and it prints.
    is_delegate = models.BooleanField(default=False)

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

    #: Fields a multi-part product leaves empty — its parts carry them instead.
    OWN_FIGURE_FIELDS = ("product_weight_kg", "length_in", "width_in", "height_in")

    def clean(self):
        if not self.is_multi_part:
            return
        filled = [f for f in self.OWN_FIGURE_FIELDS if getattr(self, f) is not None]
        if filled:
            raise ValidationError(
                {
                    filled[0]: "A multi-part product is never handled whole — "
                    "each part carries its own weight and size."
                }
            )

    @property
    def unit_cbm(self):
        """One item's own volume — used to warn when a box is mostly air."""
        return calc.cbm(self.length_in, self.width_in, self.height_in)


class DisplayProductPart(models.Model):
    """
    One separately-packed component of a display product.

    Like the product it belongs to, a part owns no box: it goes inside a
    template's carton. The reason it exists is that a product's parts need
    not travel in the *same* carton — a wreath frame packs flat with other
    frames while its trim goes in a different template altogether.
    """

    product = models.ForeignKey(
        DisplayProduct, on_delete=models.CASCADE, related_name="parts"
    )

    # Carried on the piece for the desk's own use. Nothing in packing, the
    # packing list or the invoice reads it yet — say the word and it prints.
    is_delegate = models.BooleanField(default=False)

    name = models.CharField(max_length=120, help_text="e.g. Wreath frame")
    description = models.CharField(max_length=255, blank=True)

    # Held per part: parts of different materials classify differently.
    customs_description = models.CharField(max_length=255, blank=True)
    hsn_code = models.CharField(max_length=20, blank=True)
    hts_code = models.CharField(max_length=20, blank=True)

    product_weight_kg = models.DecimalField(
        "part weight (kg)",
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="The bare part with no packaging.",
    )

    length_in = models.DecimalField(
        "part length (in)", max_digits=8, decimal_places=2, null=True, blank=True
    )
    width_in = models.DecimalField(
        "part width (in)", max_digits=8, decimal_places=2, null=True, blank=True
    )
    height_in = models.DecimalField(
        "part height (in)", max_digits=8, decimal_places=2, null=True, blank=True
    )

    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["product", "sort_order", "id"]
        verbose_name = "part"

    def __str__(self):
        return f"{self.product.style_no} — {self.name}"

    @property
    def unit_cbm(self):
        return calc.cbm(self.length_in, self.width_in, self.height_in)


def display_product_image_path(instance, filename):
    if instance.part_id:
        return f"display/parts/{instance.part_id}/{filename}"
    return f"display/products/{instance.product_id or 'unassigned'}/{filename}"


class DisplayProductImage(models.Model):
    """
    Exactly one of `product` or `part` is set. Parts get their own photos
    because a packer needs to see the component, not the assembled item.
    """

    product = models.ForeignKey(
        DisplayProduct,
        on_delete=models.CASCADE,
        related_name="images",
        null=True,
        blank=True,
    )
    part = models.ForeignKey(
        DisplayProductPart,
        on_delete=models.CASCADE,
        related_name="images",
        null=True,
        blank=True,
    )

    image = models.ImageField(upload_to=display_product_image_path)
    is_main = models.BooleanField(
        default=False, help_text="The one photo shown in lists and summaries."
    )
    sort_order = models.PositiveIntegerField(default=0)

    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Main first, so the leading image is the one lists and summaries want.
        ordering = ["-is_main", "sort_order", "id"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(product__isnull=False, part__isnull=True)
                    | models.Q(product__isnull=True, part__isnull=False)
                ),
                name="display_image_belongs_to_exactly_one_owner",
            )
        ]

    def __str__(self):
        owner = self.product or self.part
        return f"Image for {owner}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Only one photo per owner can be the main one.
        if self.is_main:
            siblings = DisplayProductImage.objects.exclude(pk=self.pk)
            if self.product_id:
                siblings = siblings.filter(product_id=self.product_id)
            else:
                siblings = siblings.filter(part_id=self.part_id)
            siblings.update(is_main=False)


class PackTemplate(TimeStampedModel):
    """
    A box design: which display products go inside and how many of each.

    The box belongs here rather than to the products. That inversion is the
    whole structural difference from Hardgoods, where a chair knows its own
    carton.
    """

    code = models.CharField(
        max_length=32,
        unique=True,
        blank=True,
        help_text="Left empty, it is assigned: T-001, T-002 …",
    )
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

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self.generate_code()
        super().save(*args, **kwargs)

    @staticmethod
    def generate_code(prefix: str = "T") -> str:
        """
        A template prefix, deliberately not a box one: a design is applied any
        number of times, so a code that read like a carton number would invite
        the reader to line the two up, and they never line up.

        Zero-padded because `Meta.ordering` sorts the code as text: without the
        padding T-10 files between T-1 and T-2 in every picker.
        """
        stem = f"{prefix}-"
        highest = (
            PackTemplate.objects.filter(code__startswith=stem).aggregate(Max("code"))[
                "code__max"
            ]
            or ""
        )
        try:
            sequence = int(highest.rsplit("-", 1)[1]) + 1
        except (IndexError, ValueError):
            sequence = 1
        return f"{stem}{sequence:03d}"

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
            self._piece_weights(), self.packing_material_weight_kg
        )

    @property
    def gross_weight_kg(self):
        return calc.mixed_carton_gross_weight(
            self._piece_weights(),
            self.packing_material_weight_kg,
            self.box_weight_kg,
        )

    def _piece_weights(self):
        # From the piece, not the product: a multi-part product has no weight
        # of its own — each of its parts carries one.
        return [(item.piece.product_weight_kg, item.quantity) for item in self.items.all()]


class PackTemplateItem(models.Model):
    template = models.ForeignKey(
        PackTemplate, on_delete=models.CASCADE, related_name="items"
    )
    product = models.ForeignKey(
        DisplayProduct, on_delete=models.PROTECT, related_name="template_items"
    )
    # Set when the product packs as parts. Two parts of one product can sit in
    # different templates, which is the whole reason this column exists.
    part = models.ForeignKey(
        DisplayProductPart,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="template_items",
    )
    # At least one, or a template could consume nothing and apply forever.
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        ordering = ["id"]
        verbose_name = "item"
        constraints = [
            # nulls_distinct=False, or Postgres would treat every whole-product
            # row as unique from every other and the rule would not bite.
            models.UniqueConstraint(
                fields=["template", "product", "part"],
                name="one_row_per_piece_per_template",
                nulls_distinct=False,
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1), name="template_item_quantity_positive"
            ),
        ]

    def __str__(self):
        return f"{self.piece_label} × {self.quantity}"

    @property
    def piece(self):
        """What this row puts in the box: a part, or the whole product."""
        return self.part or self.product

    @property
    def piece_label(self) -> str:
        if self.part_id:
            return f"{self.product.style_no} — {self.part.name}"
        return self.product.style_no


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
    """
    What one store wants, of one product. A store may take a different set of
    products from its neighbour, so the mix is per line, not per order.
    """

    order = models.ForeignKey(
        DisplayOrder, on_delete=models.CASCADE, related_name="lines"
    )
    store = models.ForeignKey(
        "masters.Store", on_delete=models.PROTECT, related_name="display_order_lines"
    )
    product = models.ForeignKey(
        DisplayProduct, on_delete=models.PROTECT, related_name="order_lines"
    )
    quantity = models.PositiveIntegerField()
    color = models.CharField(max_length=60, blank=True)
    # Where this line's store sits in the order — the column it had on the
    # buyer's sheet. Every screen and document walks the stores in this order;
    # sorting by name put "1839" before "804".
    store_position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["store_position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "store", "product"],
                name="one_display_line_per_product_per_store",
            )
        ]

    def __str__(self):
        return f"{self.store.name} · {self.product.style_no} × {self.quantity}"


class PackStep(models.Model):
    """
    One application of a template: "TPL-001, thirty-six times".

    Kept as a row rather than left implicit in the cartons because the loop is
    greedy: a choice made at step 1 is only revealed as wrong at step 4, and
    the fix is to change step 1 and replay.
    """

    order = models.ForeignKey(DisplayOrder, on_delete=models.CASCADE, related_name="steps")
    sequence = models.PositiveIntegerField()
    # A carton is never shared between two stores, so a step packs for exactly
    # one of them and the greedy loop runs inside that boundary.
    store = models.ForeignKey(
        "masters.Store", on_delete=models.PROTECT, related_name="pack_steps"
    )
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


class DisplayOrderRate(models.Model):
    """
    What one style sells for on one order.

    Not on the line: a display order lists a style once per store, and 17
    stores wanting the same wreath is one price, not seventeen. Not on the
    product either — editing the catalogue would rewrite invoices already
    sent.
    """

    order = models.ForeignKey(
        DisplayOrder, on_delete=models.CASCADE, related_name="rates"
    )
    product = models.ForeignKey(
        DisplayProduct, on_delete=models.PROTECT, related_name="order_rates"
    )
    rate_usd = models.DecimalField(
        "rate (US$)",
        max_digits=12,
        decimal_places=2,
        help_text="Unit price on this order, in US dollars. The invoice multiplies it by what ships.",
    )

    class Meta:
        ordering = ["product__style_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "product"], name="one_rate_per_product_per_order"
            )
        ]

    def __str__(self):
        return f"{self.order.number} · {self.product.style_no} @ {self.rate_usd}"


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
    # Held here rather than read through the step, because a step can be
    # cleared away and a box still has to know where it is going.
    store = models.ForeignKey(
        "masters.Store", on_delete=models.PROTECT, related_name="display_cartons"
    )
    carton_no = models.CharField(max_length=32, help_text="e.g. BOX-001")

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
    # Which part of it, when the product packs as parts. Recorded so the
    # remainder can tell "twenty tops boxed" from "twenty legs still loose".
    part = models.ForeignKey(
        DisplayProductPart,
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

    # This product's own weight only. The carton's padding sits on the carton,
    # since it belongs to the box rather than to any one thing inside it.
    net_weight_kg = models.DecimalField(
        "net weight (kg)", max_digits=10, decimal_places=3, null=True, blank=True
    )

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.piece_label} × {self.quantity}"

    @property
    def piece(self):
        """What is in the box: a part, or the whole product."""
        return self.part or self.product

    @property
    def piece_label(self) -> str:
        if self.part_id:
            return f"{self.product.style_no} — {self.part.name}"
        return self.product.style_no
