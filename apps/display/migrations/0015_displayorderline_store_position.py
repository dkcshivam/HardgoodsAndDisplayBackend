import re

from django.db import migrations, models


def _number_order(name: str) -> list:
    # Orders made before this have no sheet order on record. Buyers' sheets
    # run their store numbers upward, so reading the digits as numbers is the
    # closest guess: 804, 804 EXTRAS, 812 … 1839.
    return [
        int(chunk) if chunk.isdigit() else chunk.lower()
        for chunk in re.split(r"(\d+)", name)
    ]


def backfill(apps, schema_editor):
    Line = apps.get_model("display", "DisplayOrderLine")
    orders = Line.objects.values_list("order_id", flat=True).distinct()
    for order_id in orders:
        lines = list(Line.objects.filter(order_id=order_id).select_related("store"))
        stores = sorted(
            {line.store for line in lines}, key=lambda store: _number_order(store.name)
        )
        position = {store.id: index for index, store in enumerate(stores, start=1)}
        for line in lines:
            line.store_position = position[line.store_id]
        Line.objects.bulk_update(lines, ["store_position"])


class Migration(migrations.Migration):

    dependencies = [
        ("display", "0014_displayproduct_is_delegate_and_more"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="displayorderline",
            options={"ordering": ["store_position", "id"]},
        ),
        migrations.AddField(
            model_name="displayorderline",
            name="store_position",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.RunPython(backfill, migrations.RunPython.noop),
    ]
