from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.accounts.models import Role


def local_storage(folder) -> dict:
    """
    STORAGES that keep uploads in a folder, so no test ever writes to S3, and
    serve static files unhashed: tests never run collectstatic, so the
    manifest WhiteNoise reads would not exist for a page that renders.
    """
    return {
        "default": {
            "BACKEND": "django.core.files.storage.FileSystemStorage",
            # The prefix every image carries in the bucket, so URLs look alike.
            "OPTIONS": {"location": str(folder), "base_url": "/media/"},
        },
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


def make_user(role=Role.MERCHANT, username=None, password="a-long-pass-123", **fields):
    user = get_user_model().objects.create_user(
        username or role, password=password, **fields
    )
    user.profile.role = role
    user.profile.save()
    return user


def sign_in(client, role=Role.MERCHANT, **fields):
    user = make_user(role, **fields)
    client.force_authenticate(user)
    return user


class SignedInAPITestCase(APITestCase):
    """Every request is made by a signed-in user of `role`, as `self.user`."""

    role = Role.MERCHANT

    def setUp(self):
        super().setUp()
        self.user = sign_in(self.client, self.role)
