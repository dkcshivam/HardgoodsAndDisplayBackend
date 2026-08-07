from django.db import models

from . import calc


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class PackSpec(models.Model):
    """
    The box-and-weight block, shared by a single-box Product and by every
    Part of a multi-part one. Defined once so the weight rules cannot drift
    apart between the two paths.
    """

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

    # Properties, not columns: recomputed on every read, so they cannot go stale.

    @property
    def net_weight_kg(self):
        return calc.net_weight(self.product_weight_kg, self.packing_material_weight_kg)

    @property
    def gross_weight_kg(self):
        return calc.gross_weight(
            self.product_weight_kg,
            self.packing_material_weight_kg,
            self.box_weight_kg,
        )

    @property
    def cbm(self):
        return calc.cbm(self.box_length_in, self.box_width_in, self.box_height_in)
