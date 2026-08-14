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


class Store(TimeStampedModel):
    """
    One outlet — the address a carton is actually addressed to.

    Stores are global, not owned by a merchant: the same outlet can receive
    from any of them, so an order picks freely from the whole list. A display
    order is split across many of these, and because a carton is never shared
    between two stores, this is the boundary the packing loop runs inside.

    One free-text name, not a number and a name: outlets are written down
    however the buyer writes them — "118 Portland Pearl" — and splitting that
    into two fields only made people guess which half went where.
    """

    name = models.CharField(
        max_length=180, unique=True, help_text='Number and name, e.g. "118 Portland Pearl"'
    )

    contact_name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=40, blank=True)

    ship_line1 = models.CharField(max_length=180, blank=True)
    ship_line2 = models.CharField(max_length=180, blank=True)
    ship_city = models.CharField(max_length=80, blank=True)
    ship_state = models.CharField(max_length=80, blank=True)
    ship_postal_code = models.CharField(max_length=20, blank=True)
    ship_country = models.CharField(
        max_length=2, default="US", help_text="ISO code, e.g. US"
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name
