import os
import tempfile
from importlib import import_module
from io import StringIO
from unittest import mock

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from apps.common.testing import local_storage

from .models import Profile, Role, role_of

User = get_user_model()


class ProfileTests(TestCase):
    def test_a_new_user_is_a_merchant(self):
        user = User.objects.create_user("asha", password="x")
        self.assertEqual(user.profile.role, Role.MERCHANT)

    def test_a_new_superuser_is_an_admin(self):
        user = User.objects.create_superuser("root", "root@example.com", "x")
        self.assertEqual(user.profile.role, Role.ADMIN)

    def test_createsuperuser_makes_an_admin(self):
        with mock.patch.dict(os.environ, {"DJANGO_SUPERUSER_PASSWORD": "a-long-pass-123"}):
            call_command(
                "createsuperuser",
                interactive=False,
                username="boss",
                email="boss@example.com",
                stdout=StringIO(),
            )
        self.assertEqual(User.objects.get(username="boss").profile.role, Role.ADMIN)

    def test_the_database_refuses_an_unknown_role(self):
        user = User.objects.create_user("asha", password="x")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Profile.objects.filter(user=user).update(role="owner")

    def test_a_superuser_is_an_admin_whatever_the_profile_says(self):
        user = User.objects.create_superuser("root", "root@example.com", "x")
        Profile.objects.filter(user=user).update(role=Role.MERCHANT)
        user.refresh_from_db()
        self.assertEqual(role_of(user), Role.ADMIN)

    def test_a_user_without_a_profile_gets_the_least_role(self):
        user = User.objects.create_user("asha", password="x")
        user.profile.delete()
        self.assertEqual(role_of(User.objects.get(pk=user.pk)), Role.MERCHANT)


class ExistingUsersMigrationTests(TestCase):
    def test_existing_superusers_become_admins_and_others_merchants(self):
        root = User.objects.create_superuser("root", "root@example.com", "x")
        clerk = User.objects.create_user("clerk", password="x")
        Profile.objects.all().delete()

        migration = import_module("apps.accounts.migrations.0002_profiles_for_existing_users")
        migration.give_every_user_a_profile(django_apps, None)

        self.assertEqual(Profile.objects.get(user=root).role, Role.ADMIN)
        self.assertEqual(Profile.objects.get(user=clerk).role, Role.MERCHANT)


@override_settings(STORAGES=local_storage(tempfile.mkdtemp()))
class UserAdminTests(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser("root", "root@example.com", "x"))

    def test_adding_a_user_in_the_admin_gives_it_one_profile(self):
        response = self.client.post(
            reverse("admin:auth_user_add"),
            {
                "username": "asha",
                "usable_password": "true",
                "password1": "a-long-pass-123",
                "password2": "a-long-pass-123",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(User.objects.get(username="asha").profile.role, Role.MERCHANT)

    def test_the_role_is_edited_on_the_user_page(self):
        user = User.objects.create_user("asha", password="x")
        response = self.client.get(reverse("admin:auth_user_change", args=[user.pk]))
        self.assertContains(response, 'name="profile-0-role"')

    def test_the_user_list_filters_by_role(self):
        User.objects.create_user("asha", password="x")
        response = self.client.get(
            reverse("admin:auth_user_changelist"), {"profile__role__exact": Role.MERCHANT}
        )
        self.assertEqual(
            [user.username for user in response.context["cl"].result_list], ["asha"]
        )
