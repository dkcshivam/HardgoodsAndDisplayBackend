"""
The catalogue — packing recipes.

A Product record here is not a thing for sale. It has no price and no
stock count. Every field answers one question: how does this go in a box?
Describe a table once, and the app can pack it correctly forever after.
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
    One SKU, identified by its Style No.

    A product takes one of two shapes, chosen by `is_multi_part`:

    SINGLE-BOX (is_multi_part=False)
        The whole item ships in one carton. The inherited PackSpec fields
        (box type, box dimensions, the three weights) describe that carton.
        `pack_per_box` says how many units fit in it.

    MULTI-PART (is_multi_part=True)
        The item ships disassembled across several cartons — a table top in
        one, its legs in another. There is no product-level box, because the
        assembled item never goes in one. The inherited PackSpec fields stay
        empty and every Part carries its own instead.

        The assembled_* fields below record the finished item's size and
        weight. They are reference information for humans only and take no
        part in any packing calculation.
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
    product_group = models.ForeignKey(
        "masters.ProductGroup",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
    )

    # Customs paperwork. For a multi-part product these live on each part
    # instead, because different parts can classify differently — a wooden
    # tray base and its brass handles have different HSN codes.
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

    def clean(self):
        if self.is_multi_part and self.box_type_id:
            raise ValidationError(
                {
                    "box_type": "A multi-part product has no box of its own — "
                    "each part carries its own box."
                }
            )

    def save(self, *args, **kwargs):
        if not self.is_multi_part:
            self.apply_box_type_dimensions()
        super().save(*args, **kwargs)

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
    One separately-boxed component of a multi-part product.

    A part carries exactly the same depth of data as a whole single-box
    product, because as far as the shipment is concerned that is what it
    is: an item in its own carton with its own weight and its own customs
    classification.
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

    def save(self, *args, **kwargs):
        self.apply_box_type_dimensions()
        super().save(*args, **kwargs)


def product_image_path(instance, filename):
    return f"products/{instance.product_id or 'unassigned'}/{filename}"


class ProductImage(models.Model):
    """
    A photo of a product or of one of its parts.

    Exactly one of `product` or `part` is set. Parts get their own photos
    because a warehouse packer needs to see the specific component, from
    several angles, not the assembled item.
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
        ordering = ["sort_order", "id"]
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
