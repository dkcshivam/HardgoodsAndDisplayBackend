"""
Order lines become per-store.

Existing orders carried a single ship-to address, so each one gets a "MAIN"
store built from that address — nothing loses its destination on the way
through.
"""

import django.db.models.deletion
from django.db import migrations, models


def build_stores(apps, schema_editor):
    DisplayOrder = apps.get_model("display", "DisplayOrder")
    Store = apps.get_model("masters", "Store")

    for order in DisplayOrder.objects.select_related("merchant"):
        if not order.lines.exists():
            continue
        store, _ = Store.objects.get_or_create(
            merchant=order.merchant,
            code="MAIN",
            defaults={
                "name": f"{order.merchant.name} — main",
                "ship_line1": order.ship_line1,
                "ship_line2": order.ship_line2,
                "ship_city": order.ship_city,
                "ship_state": order.ship_state,
                "ship_postal_code": order.ship_postal_code,
                "ship_country": order.ship_country or "US",
            },
        )
        order.lines.update(store=store)


def drop_stores(apps, schema_editor):
    # Only the ones this migration could have made; a store someone typed by
    # hand is not ours to delete.
    Store = apps.get_model("masters", "Store")
    Store.objects.filter(code="MAIN", display_order_lines__isnull=False).distinct(
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("display", "0004_remove_packtemplateitem_one_row_per_product_per_template_and_more"),
        ("masters", "0003_store"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="displayorderline",
            name="one_display_line_per_product_per_order",
        ),
        migrations.AddField(
            model_name="displayorderline",
            name="store",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="display_order_lines",
                to="masters.store",
            ),
        ),
        migrations.RunPython(build_stores, drop_stores),
    ]
