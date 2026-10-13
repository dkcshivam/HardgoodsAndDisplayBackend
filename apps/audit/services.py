import json
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal

from django.core.serializers.json import DjangoJSONEncoder
from django.db.models import Count, Sum
from django.db.models.fields.files import FieldFile

from .models import Action, AuditEvent

# Stamped on every save, so they would turn every edit into a change.
NOISE = {"created_at", "updated_at", "uploaded_at", "last_login", "date_joined"}
# Compared as stored, so a change still shows, but only ever recorded masked.
SECRETS = {"password"}
MASK = "***"


@dataclass(frozen=True)
class Target:
    type: str
    id: str
    repr: str


class Rows(list):
    """A related collection in a snapshot, diffed row by row rather than whole."""


def target_of(instance) -> Target:
    return Target(instance._meta.label_lower, str(instance.pk), describe(instance))


def describe(instance) -> str:
    for field in ("number", "style_no", "username"):
        if value := getattr(instance, field, None):
            return str(value)
    return str(instance)


def fresh(instance):
    # Read back what was stored, not what the serializer handed the instance:
    # 6 and 6.000 are the same weight and must not read as a change.
    return type(instance)._base_manager.get(pk=instance.pk)


def snapshot(instance, related=()) -> dict:
    values = {
        field.name: _plain(getattr(instance, field.attname))
        for field in instance._meta.concrete_fields
        if not field.primary_key and field.name not in NOISE
    }
    for name in related:
        values[name] = _rows(getattr(instance, name))
    return values


def _rows(manager) -> Rows:
    # Without ids: order lines and template items are rewritten on every save,
    # so their ids change even when nothing else does.
    fields = [
        field
        for field in manager.model._meta.concrete_fields
        if not field.primary_key
        and field.name != manager.field.name
        and field.name not in NOISE
    ]
    rows = [
        {
            field.name: _plain(row[field.attname])
            for field in fields
            if not _blank(row[field.attname])
        }
        for row in manager.values(*(field.attname for field in fields))
    ]
    return Rows(sorted(rows, key=_canonical))


def diff(before: dict | None, after: dict | None) -> dict:
    """
    {field: [before, after]} for each field that differs; None for the side
    that does not exist yet, or any more. A collection lists only the rows it
    lost and the rows it gained, so one changed line of five hundred stays one.
    """
    before, after = before or {}, after or {}
    changes = {}
    for field in {**before, **after}:
        old, new = before.get(field), after.get(field)
        if old == new or (_blank(old) and _blank(new)):
            continue
        if field in SECRETS:
            old, new = _mask(old), _mask(new)
        elif isinstance(old, Rows) and isinstance(new, Rows):
            old, new = _row_changes(old, new)
        changes[field] = [old, new]
    return changes


def _row_changes(old: Rows, new: Rows) -> tuple[list, list]:
    kept, made = Counter(map(_canonical, old)), Counter(map(_canonical, new))
    return (
        [json.loads(row) for row in sorted((kept - made).elements())],
        [json.loads(row) for row in sorted((made - kept).elements())],
    )


def summary(before: dict | None, after: dict | None) -> dict:
    """
    [before, after] for every key, changed or not, so an action on an order
    says what it acted on. Status is the exception: news only when it moved.
    """
    before, after = before or {}, after or {}
    changes = {key: [before.get(key), after.get(key)] for key in {**before, **after}}
    if "status" in changes and changes["status"][0] == changes["status"][1]:
        del changes["status"]
    return changes


def plan_summary(order) -> dict:
    # Three numbers, whatever the plan's size: a 1 200-carton save is one row.
    totals = order.cartons.aggregate(
        count=Count("id"), weight=Sum("gross_weight_kg")
    )
    return {
        "status": order.status,
        "carton_count": totals["count"],
        "total_gross_weight_kg": totals["weight"] or Decimal("0.000"),
    }


def step_summary(step) -> dict | None:
    if step is None:
        return None
    return {
        "sequence": step.sequence,
        "store": step.store.name,
        "template": step.template.code,
        "count": step.count,
    }


def record(actor, action: Action, target, changes: dict | None = None) -> AuditEvent:
    if not isinstance(target, Target):
        target = target_of(target)
    if not getattr(actor, "is_authenticated", False):
        actor = None
    return AuditEvent.objects.create(
        actor=actor,
        actor_name=(actor.get_full_name() or actor.username)[:255] if actor else "",
        action=action,
        target_type=target.type,
        target_id=target.id,
        target_repr=target.repr[:255],
        changes=_plain(changes or {}),
    )


def record_create(actor, instance, related=()) -> None:
    record(actor, Action.CREATE, instance, diff(None, snapshot(fresh(instance), related)))


@contextmanager
def recording_update(actor, instance, related=()):
    before = snapshot(instance, related)
    yield
    after = fresh(instance)
    if changes := diff(before, snapshot(after, related)):
        record(actor, Action.UPDATE, after, changes)


@contextmanager
def recording_delete(actor, instance, related=()):
    # Taken first: once deleted, the instance has lost its pk, and a photo
    # its file name.
    target, before = target_of(instance), snapshot(instance, related)
    yield
    record(actor, Action.DELETE, target, diff(before, None))


def _plain(value):
    if isinstance(value, FieldFile):
        return value.name or None
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def _blank(value) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _mask(value):
    return MASK if value else None


def _canonical(row: dict) -> str:
    return json.dumps(row, sort_keys=True)
