"""
Locks the store in, once 0005 has given every existing line one.

Separate from 0005 because Postgres will not alter a table that still has
trigger events pending from the backfill's inserts.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("display", "0005_display_order_line_store"),
    ]

    operations = [
        migrations.AlterField(
            model_name="displayorderline",
            name="store",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="display_order_lines",
                to="masters.store",
            ),
        ),
        migrations.AlterModelOptions(
            name="displayorderline",
            options={"ordering": ["store__code", "id"]},
        ),
        migrations.AddConstraint(
            model_name="displayorderline",
            constraint=models.UniqueConstraint(
                fields=("order", "store", "product"),
                name="one_display_line_per_product_per_store",
            ),
        ),
    ]
