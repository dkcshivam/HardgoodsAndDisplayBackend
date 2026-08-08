"""
Packing recipes. Not sale items — no price, no stock. Every field answers
one question: how does this go in a box?
"""

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models

from apps.common.models import PackSpec, TimeStampedModel


class ProductStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    INACTIVE = "inactive", "Inactive"


class Product(PackSpec, TimeStampedModel):
    """
    One SKU, in one of two shapes.

    Single-box (is_multi_part=False): the inherited PackSpec describes the
    one carton, and pack_per_box says how many units fit in it.

    Multi-part (True): ships disassembled, so there is no product-level box.
    The PackSpec fields stay empty and every Part carries its own.
    """

    style_no = models.CharField(
        max_length=64,
        unique=True,
        help_text="Unique SKU code, e.g. DKC-TBL-OAK-01",
    )
    description = models.CharField(
        max_length=255,
        help_text="Internal or trade name, e.g. Oak Dining Table",
    )

    category = models.ForeignKey(
        "masters.Category",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="products",
    )
    # For a multi-part product these live on each part instead: a wooden base
    # and its brass handles classify under different HSN codes.
    customs_description = models.CharField(
        max_length=255,
        blank=True,
        help_text="Formal name for shipping documents; may differ from the description.",
    )
    hsn_code = models.CharField(
        max_length=20, blank=True, help_text="Harmonized System Nomenclature code."
    )

    is_multi_part = models.BooleanField(
        default=False,
        help_text="On = ships disassembled in several cartons, one per part.",
    )
    is_fragile = models.BooleanField(
        default=False, help_text="Flags careful handling on documents."
    )
    status = models.CharField(
        max_length=10, choices=ProductStatus.choices, default=ProductStatus.ACTIVE
    )

    # Reference only — the finished, put-together item.
    assembled_length_in = models.DecimalField(
        "assembled length (in)", max_digits=8, decimal_places=2, null=True, blank=True
    )
    assembled_width_in = models.DecimalField(
        "assembled width (in)", max_digits=8, decimal_places=2, null=True, blank=True
    )
    assembled_height_in = models.DecimalField(
        "assembled height (in)", max_digits=8, decimal_places=2, null=True, blank=True
    )
    assembled_weight_kg = models.DecimalField(
        "assembled weight (kg)", max_digits=10, decimal_places=3, null=True, blank=True
    )

    pack_per_box = models.PositiveIntegerField(
        default=1,
        validators=[MinValueValidator(1)],
        help_text="Single-box products only: how many units fit in one carton.",
    )

    class Meta:
        ordering = ["style_no"]

    def __str__(self):
        return f"{self.style_no} · {self.description}"

    #: PackSpec fields that must stay empty on a multi-part product.
    OWN_BOX_FIELDS = (
        "box_length_in",
        "box_width_in",
        "box_height_in",
        "product_weight_kg",
        "box_weight_kg",
        "packing_material_weight_kg",
    )

    def clean(self):
        if not self.is_multi_part:
            return
        filled = [f for f in self.OWN_BOX_FIELDS if getattr(self, f) is not None]
        if filled:
            raise ValidationError(
                {
                    filled[0]: "A multi-part product has no box of its own — "
                    "each part carries its own box and weights."
                }
            )

    # ── Totals across parts ──────────────────────────────────────────

    @property
    def total_shipping_weight_kg(self):
        """Gross weight of every carton this product ships in."""
        if not self.is_multi_part:
            return self.gross_weight_kg
        return sum((part.gross_weight_kg for part in self.parts.all()), start=0)

    @property
    def total_shipping_cbm(self):
        """Volume of every carton this product ships in."""
        if not self.is_multi_part:
            return self.cbm
        return sum((part.cbm for part in self.parts.all()), start=0)

    @property
    def carton_count_per_unit(self):
        """How many cartons one ordered unit produces."""
        return self.parts.count() if self.is_multi_part else 1


class ProductPart(PackSpec):
    """
    One separately-boxed component. Carries the same depth of data as a
    single-box product, because to the shipment that is what it is.
    """

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="parts")

    name = models.CharField(max_length=120, help_text="e.g. Table top")
    description = models.CharField(max_length=255, blank=True)

    customs_description = models.CharField(max_length=255, blank=True)
    hsn_code = models.CharField(max_length=20, blank=True)

    # The part itself, not its box.
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


def product_image_path(instance, filename):
    if instance.part_id:
        return f"products/parts/{instance.part_id}/{filename}"
    return f"products/{instance.product_id or 'unassigned'}/{filename}"


class ProductImage(models.Model):
    """
    Exactly one of `product` or `part` is set. Parts get their own photos
    because a packer needs to see the component, not the assembled item.
    """

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="images",
        null=True,
        blank=True,
    )
    part = models.ForeignKey(
        ProductPart,
        on_delete=models.CASCADE,
        related_name="images",
        null=True,
        blank=True,
    )

    image = models.ImageField(upload_to=product_image_path)
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
                name="image_belongs_to_exactly_one_owner",
            )
        ]

    def __str__(self):
        owner = self.product or self.part
        return f"Image for {owner}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Only one photo per owner can be the main one.
        if self.is_main:
            siblings = ProductImage.objects.exclude(pk=self.pk)
            if self.product_id:
                siblings = siblings.filter(product_id=self.product_id)
            else:
                siblings = siblings.filter(part_id=self.part_id)
            siblings.update(is_main=False)
