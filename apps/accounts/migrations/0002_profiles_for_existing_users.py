from django.conf import settings
from django.db import migrations


def give_every_user_a_profile(apps, schema_editor):
    User = apps.get_model(settings.AUTH_USER_MODEL)
    Profile = apps.get_model("accounts", "Profile")
    # The accounts made before roles existed are the superusers who ran the
    # admin; they keep running it.
    Profile.objects.bulk_create(
        Profile(user=user, role="admin" if user.is_superuser else "merchant")
        for user in User.objects.filter(profile__isnull=True)
    )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]

    operations = [
        migrations.RunPython(give_every_user_a_profile, migrations.RunPython.noop)
    ]
