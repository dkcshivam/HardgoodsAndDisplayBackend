from django.db import migrations, models
from django.db.models.functions import Left


def seed_from_description(apps, schema_editor):
    """
    Products predating the field have no buyer's name, and the description is
    the closest thing they have to one — better on a box sticker than a blank.
    Trimmed because a description may run longer than a style name may.
    """
    product = apps.get_model("catalog", "Product")
    product.objects.filter(style_name="").update(
        style_name=Left("description", 180)
    )


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0003_alter_productimage_options_remove_product_is_fragile"),
    ]

    operations = [
        migrations.AddField(
            model_name="product",
            name="style_name",
            field=models.CharField(
                blank=True,
                help_text="The buyer's name for the style, e.g. Oak Dining Table.",
                max_length=180,
            ),
        ),
        # Not reversed: dropping the column takes the names with it, and a
        # reverse that blanked them would also blank the ones typed since.
        migrations.RunPython(seed_from_description, migrations.RunPython.noop),
    ]
