from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.test import TestCase

from apps.common.testing import make_user

from .models import Action, AppendOnlyError, AuditEvent


def event(**fields):
    return AuditEvent.objects.create(
        **{
            "action": Action.UPDATE,
            "target_type": "masters.category",
            "target_id": "1",
            "target_repr": "Lighting",
            "changes": {"name": ["Lamps", "Lighting"]},
            **fields,
        }
    )


class AppendOnlyTests(TestCase):
    def setUp(self):
        self.event = event(actor=make_user(username="asha"), actor_name="asha")

    def assertUnchanged(self):
        stored = AuditEvent.objects.get(pk=self.event.pk)
        self.assertEqual(stored.target_repr, "Lighting")
        self.assertEqual(stored.changes, {"name": ["Lamps", "Lighting"]})

    def test_the_model_refuses_to_change_or_delete_an_event(self):
        self.event.target_repr = "Something else"
        with self.assertRaises(AppendOnlyError):
            self.event.save()
        with self.assertRaises(AppendOnlyError):
            self.event.delete()
        with self.assertRaises(AppendOnlyError):
            AuditEvent.objects.filter(pk=self.event.pk).update(target_repr="x")
        with self.assertRaises(AppendOnlyError):
            AuditEvent.objects.all().delete()
        self.assertUnchanged()

    def test_the_database_refuses_to_change_or_delete_an_event(self):
        for sql in (
            "UPDATE audit_auditevent SET target_repr = 'x' WHERE id = %s",
            "DELETE FROM audit_auditevent WHERE id = %s",
        ):
            with self.subTest(sql=sql.split()[0]):
                with self.assertRaises(IntegrityError), transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute(sql, [self.event.pk])
        self.assertUnchanged()

    def test_the_database_refuses_an_unknown_action(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            event(action="erase")

    def test_an_actor_with_events_cannot_be_deleted(self):
        with self.assertRaises(ProtectedError):
            self.event.actor.delete()
