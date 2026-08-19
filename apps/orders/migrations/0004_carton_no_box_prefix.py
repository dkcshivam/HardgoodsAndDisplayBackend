from django.db import migrations, models
from django.db.models import Value
from django.db.models.functions import Replace


def to_box(apps, schema_editor):
    _swap(apps, "CTN-", "BOX-")


def to_ctn(apps, schema_editor):
    _swap(apps, "BOX-", "CTN-")


def _swap(apps, old, new):
    carton = apps.get_model("orders", "Carton")
    carton.objects.filter(carton_no__startswith=old).update(
        carton_no=Replace("carton_no", Value(old), Value(new))
    )


class Migration(migrations.Migration):

    dependencies = [
        ("orders", "0003_orderline_color"),
    ]

    operations = [
        migrations.AlterField(
            model_name="carton",
            name="carton_no",
            field=models.CharField(help_text="e.g. BOX-001", max_length=32),
        ),
        # Boxes packed before the rename would otherwise print CTN while
        # everything built after it prints BOX, on the same packing list.
        migrations.RunPython(to_box, to_ctn),
    ]
