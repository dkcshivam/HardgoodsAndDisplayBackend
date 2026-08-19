from django.db import migrations, models
from django.db.models import Value
from django.db.models.functions import Replace


def to_box(apps, schema_editor):
    _swap(apps, "CTN-", "BOX-")


def to_ctn(apps, schema_editor):
    _swap(apps, "BOX-", "CTN-")


def _swap(apps, old, new):
    carton = apps.get_model("display", "DisplayCarton")
    # The prefix is uniform, so the per-order uniqueness of the number the
    # rename leaves behind is the uniqueness it already had.
    carton.objects.filter(carton_no__startswith=old).update(
        carton_no=Replace("carton_no", Value(old), Value(new))
    )


class Migration(migrations.Migration):

    dependencies = [
        ("display", "0011_alter_packtemplate_code"),
    ]

    operations = [
        migrations.AlterField(
            model_name="displaycarton",
            name="carton_no",
            field=models.CharField(help_text="e.g. BOX-001", max_length=32),
        ),
        migrations.AlterField(
            model_name="packtemplate",
            name="code",
            field=models.CharField(
                blank=True,
                help_text="Left empty, it is assigned: T-001, T-002 …",
                max_length=32,
                unique=True,
            ),
        ),
        migrations.RunPython(to_box, to_ctn),
    ]
