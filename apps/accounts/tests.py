import os
import tempfile
from importlib import import_module
from io import StringIO
from unittest import mock

from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from apps.common.testing import local_storage, make_user

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


class AuthTests(APITestCase):
    password = "a-long-pass-123"

    def setUp(self):
        # The login throttle counts in the cache, which outlives a test.
        cache.clear()
        self.user = make_user(
            Role.SENIOR_MERCHANT,
            username="asha",
            first_name="Asha",
            last_name="Rao",
            email="asha@example.com",
        )

    def login(self, username="asha", password=None):
        return self.client.post(
            "/api/auth/login/",
            {"username": username, "password": password or self.password},
            format="json",
        )

    def refresh(self, token):
        return self.client.post("/api/auth/refresh/", {"refresh": token}, format="json")

    def bearer(self, access):
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

    def deactivate(self):
        self.user.is_active = False
        self.user.save()

    def test_the_api_refuses_a_request_without_a_token(self):
        response = self.client.get("/api/orders/")
        self.assertEqual(response.status_code, 401)
        self.assertIn("Bearer", response["WWW-Authenticate"])

    def test_the_api_lets_in_a_request_with_a_token_from_login(self):
        self.bearer(self.login().data["access"])
        self.assertEqual(self.client.get("/api/orders/").status_code, 200)

    def test_login_returns_both_tokens_and_the_user(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["access"])
        self.assertTrue(response.data["refresh"])
        user = response.data["user"]
        self.assertEqual(user["username"], "asha")
        self.assertEqual(user["full_name"], "Asha Rao")
        self.assertEqual(user["role"], "senior_merchant")
        self.assertEqual(user["role_label"], "Senior Merchant")
        self.assertIsNotNone(user["last_login"])

    def test_login_refuses_a_wrong_password(self):
        response = self.login(password="not-the-password")
        self.assertEqual(response.status_code, 401)
        self.assertIn("detail", response.data)

    def test_login_refuses_an_inactive_user(self):
        self.deactivate()
        self.assertEqual(self.login().status_code, 401)

    def test_login_is_throttled(self):
        for _ in range(10):
            self.assertEqual(self.login(password="guess").status_code, 401)
        self.assertEqual(self.login().status_code, 429)

    def test_refresh_hands_back_a_new_refresh_token_and_retires_the_old(self):
        old = self.login().data["refresh"]

        response = self.refresh(old)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["access"])
        self.assertNotEqual(response.data["refresh"], old)

        self.assertEqual(self.refresh(old).status_code, 401)
        self.assertEqual(self.refresh(response.data["refresh"]).status_code, 200)

    def test_refresh_refuses_an_inactive_user(self):
        token = self.login().data["refresh"]
        self.deactivate()
        self.assertEqual(self.refresh(token).status_code, 401)

    def test_refresh_refuses_garbage(self):
        self.assertEqual(self.refresh("not-a-token").status_code, 401)

    def test_logout_blacklists_the_refresh_token(self):
        tokens = self.login().data
        self.bearer(tokens["access"])

        response = self.client.post(
            "/api/auth/logout/", {"refresh": tokens["refresh"]}, format="json"
        )
        self.assertEqual(response.status_code, 204)
        self.assertEqual(self.refresh(tokens["refresh"]).status_code, 401)

    def test_logout_needs_a_token(self):
        refresh = self.login().data["refresh"]
        response = self.client.post("/api/auth/logout/", {"refresh": refresh}, format="json")
        self.assertEqual(response.status_code, 401)

    def test_me_is_the_signed_in_user(self):
        self.bearer(self.login().data["access"])
        response = self.client.get("/api/auth/me/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["id"], self.user.pk)
        self.assertEqual(response.data["role"], "senior_merchant")

    def test_a_user_with_no_name_is_called_by_username(self):
        make_user(username="ravi")
        self.bearer(self.login("ravi").data["access"])
        self.assertEqual(self.client.get("/api/auth/me/").data["full_name"], "ravi")

    def test_a_superuser_is_shown_as_an_admin(self):
        User.objects.create_superuser("root", "root@example.com", self.password)
        Profile.objects.filter(user__username="root").update(role=Role.MERCHANT)
        self.bearer(self.login("root").data["access"])
        self.assertEqual(self.client.get("/api/auth/me/").data["role"], "admin")

    def test_an_inactive_users_token_is_refused(self):
        self.bearer(self.login().data["access"])
        self.deactivate()
        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)

    def change_password(self, current, new):
        return self.client.post(
            "/api/auth/password/",
            {"current_password": current, "new_password": new},
            format="json",
        )

    def test_changing_the_password_signs_out_every_session(self):
        tokens = self.login().data
        self.bearer(tokens["access"])

        response = self.change_password(self.password, "a-new-long-pass-456")
        self.assertEqual(response.status_code, 204)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("a-new-long-pass-456"))

        self.assertEqual(self.client.get("/api/auth/me/").status_code, 401)
        self.assertEqual(self.refresh(tokens["refresh"]).status_code, 401)
        self.assertEqual(self.login(password="a-new-long-pass-456").status_code, 200)

    def test_changing_the_password_needs_the_current_one(self):
        self.bearer(self.login().data["access"])
        response = self.change_password("not-the-password", "a-new-long-pass-456")
        self.assertEqual(response.status_code, 400)
        self.assertIn("current_password", response.data)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(self.password))

    def test_a_weak_new_password_is_refused(self):
        self.bearer(self.login().data["access"])
        response = self.change_password(self.password, "12345")
        self.assertEqual(response.status_code, 400)
        self.assertIn("new_password", response.data)
