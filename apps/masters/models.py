"""Master data — set up once, referenced everywhere, outlives any shipment."""

from django.db import models

from apps.common.calc import cbm
from apps.common.models import TimeStampedModel


class BoxType(TimeStampedModel):
    """
    A reusable carton specification — a kind of box, not a physical one.
    The taped-up box that ships is a Carton (apps.orders).
    """

    code = models.CharField(max_length=32, unique=True, help_text="e.g. STD-M")
    name = models.CharField(max_length=120, help_text="e.g. Standard Medium")

    length_in = models.DecimalField("length (in)", max_digits=8, decimal_places=2)
    width_in = models.DecimalField("width (in)", max_digits=8, decimal_places=2)
    height_in = models.DecimalField("height (in)", max_digits=8, decimal_places=2)

    max_weight_kg = models.DecimalField(
        "max weight (kg)",
        max_digits=10,
        decimal_places=3,
        null=True,
        blank=True,
        help_text="Optional. What this carton can safely carry.",
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["code"]
        verbose_name = "box type"

    def __str__(self):
        return f"{self.code} · {self.name}"

    @property
    def cbm(self):
        return cbm(self.length_in, self.width_in, self.height_in)


class Category(TimeStampedModel):
    """Set once per product, never per part. A list column, not a grouping."""

    name = models.CharField(max_length=80, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class ProductGroup(TimeStampedModel):
    """
    Products sharing a packing instruction. Cuts across categories — one
    group can hold a table, a chair and a stool.
    """

    name = models.CharField(max_length=120, unique=True)
    remark = models.TextField(blank=True, help_text="Packing instruction for the group.")

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Merchant(TimeStampedModel):
    """The customer we ship to — Urban Outfitters, West Elm, Terrain."""

    code = models.CharField(max_length=16, unique=True, help_text="e.g. UO")
    name = models.CharField(max_length=180)

    contact_name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)

    city = models.CharField(max_length=80, blank=True)
    country = models.CharField(max_length=2, blank=True, help_text="ISO code, e.g. US")

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.code} · {self.name}"
