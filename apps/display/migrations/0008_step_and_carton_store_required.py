"""Separate from 0007 so the backfill's writes settle before the alter."""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("display", "0007_step_and_carton_store"),
    ]

    operations = [
        migrations.AlterField(
            model_name="packstep",
            name="store",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="pack_steps",
                to="masters.store",
            ),
        ),
        migrations.AlterField(
            model_name="displaycarton",
            name="store",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="display_cartons",
                to="masters.store",
            ),
        ),
    ]
