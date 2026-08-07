"""Master data — set up once, referenced everywhere, outlives any shipment."""

from django.db import models

from apps.common.models import TimeStampedModel


class Category(TimeStampedModel):
    """Set once per product, never per part. A list column, not a grouping."""

    name = models.CharField(max_length=80, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

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
