"""
Steps and cartons learn which store they are for.

Anything already packed belonged to an order with one destination, so it is
assigned that order's store — the one 0005 built from its ship-to address.
"""

import django.db.models.deletion
from django.db import migrations, models


def assign_store(apps, schema_editor):
    DisplayOrder = apps.get_model("display", "DisplayOrder")

    for order in DisplayOrder.objects.all():
        line = order.lines.first()
        if line is None:
            # No lines means no demand, so nothing can have been packed.
            continue
        order.steps.update(store_id=line.store_id)
        order.cartons.update(store_id=line.store_id)


class Migration(migrations.Migration):
    dependencies = [
        ("display", "0006_display_order_line_store_required"),
    ]

    operations = [
        migrations.AddField(
            model_name="packstep",
            name="store",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="pack_steps",
                to="masters.store",
            ),
        ),
        migrations.AddField(
            model_name="displaycarton",
            name="store",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="display_cartons",
                to="masters.store",
            ),
        ),
        migrations.RunPython(assign_store, migrations.RunPython.noop),
    ]
