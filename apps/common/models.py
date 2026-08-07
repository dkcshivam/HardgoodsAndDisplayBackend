"""
Abstract models — shared field blocks that other models inherit.
Nothing here creates a database table.
"""

from django.db import models

from . import calc


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class PackSpec(models.Model):
    """
    The box-and-weight block.

    It appears identically in two places: on a single-box Product, and on
    every Part of a multi-part Product. Defining it once means the weight
    rules can never drift apart between the two.

    Three weights are entered by a person. Two are derived and never stored
    as editable fields — see the properties at the bottom.
    """

    box_type = models.ForeignKey(
        "masters.BoxType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(app_label)s_%(class)s_set",
        help_text="Picking a type fills the dimensions below; they stay editable.",
    )

    box_length_in = models.DecimalField(
        "box length (in)", max_digits=8, decimal_places=2, null=True, blank=True
    )
    box_width_in = models.DecimalField(
        "box width (in)", max_digits=8, decimal_places=2, null=True, blank=True
    )
    box_height_in = models.DecimalField(
        "box height (in)", max_digits=8, decimal_places=2, null=True, blank=True
    )

    product_weight_kg = models.DecimalField(
        "product weight (kg)",
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="The bare item with no packaging.",
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

    class Meta:
        abstract = True

    # ── Derived values ───────────────────────────────────────────────
    # Properties, not columns. They cannot go stale, because they are
    # recomputed from the three entered weights every time they are read.

    @property
    def net_weight_kg(self):
        """Everything inside the box: product + packing material."""
        return calc.net_weight(self.product_weight_kg, self.packing_material_weight_kg)

    @property
    def gross_weight_kg(self):
        """The whole sealed carton: net + the empty box."""
        return calc.gross_weight(
            self.product_weight_kg,
            self.packing_material_weight_kg,
            self.box_weight_kg,
        )

    @property
    def cbm(self):
        """Volume of the shipping box in cubic metres."""
        return calc.cbm(self.box_length_in, self.box_width_in, self.box_height_in)

    def apply_box_type_dimensions(self):
        """Fill any blank box dimension from the chosen box type."""
        if not self.box_type:
            return
        if self.box_length_in is None:
            self.box_length_in = self.box_type.length_in
        if self.box_width_in is None:
            self.box_width_in = self.box_type.width_in
        if self.box_height_in is None:
            self.box_height_in = self.box_type.height_in
