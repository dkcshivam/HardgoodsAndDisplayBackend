# DKC Packing — Backend

Django REST API. Turns an order into a verified carton plan.

**[ARCHITECTURE.md](ARCHITECTURE.md) is the spec** — data model, business rules,
API surface. Read the relevant section before changing behaviour. If code and
that file disagree, one of them is a bug; decide which, then fix it.

The frontend lives in a separate repo, `HardgoodsAndDisplayFrontend`. Any change
to a serializer field name or endpoint shape breaks it — say so in the commit
message so the matching frontend change is not forgotten.

## Commands

```bash
docker compose up -d                                # db + api
docker compose exec backend python manage.py seed_demo      # hardgoods sample data
docker compose exec backend python manage.py seed_display   # display sample data
docker compose exec backend python manage.py test   # must pass
docker compose exec backend python manage.py makemigrations
docker compose exec backend python manage.py createsuperuser
uv add <package>                                    # deps live in pyproject.toml + uv.lock
```

API http://localhost:8000/api · Admin http://localhost:8000/admin

## Layout

```
apps/common     calc.py (source of truth for the maths), PackSpec abstract model
apps/masters    Category, Merchant
apps/catalog    Product, ProductPart, ProductImage
apps/orders     Order, Carton, CartonContent + services.py (the packing engine)
apps/display    DisplayProduct, PackTemplate, PackStep, DisplayCarton
                + services.py (the step engine) — see ARCHITECTURE.md §10
config          settings, urls
```

## Rules

- **Units**: inches for dimensions, kilograms for weights, CBM for volume.
  Every field carries its unit as a suffix. Never mix.
- **Derived values are never stored.** `net_weight_kg`, `gross_weight_kg`, `cbm`
  are properties recomputed on read. Do not add columns for them.
- **Decimal, never float**, for anything that reaches a customs document.
- Business rules belong in `apps/orders/services.py`, not in views or serializers.
- Rules that must hold get enforced twice: in application code for the error
  message, and as a database constraint for the guarantee.
- A second `@action` on an existing `url_path` silently shadows the first.
  Give one action `methods=["get", "put"]` instead.

## Style

Comments explain *why*, not *what*. No file-header block comments, no docstrings
on obvious functions. One or two lines is the budget for a non-obvious decision.

## Git

Small commits, one feature each. A single imperative line under ~60 characters,
plain English, no trailers, no attribution footers, no emoji.

```
add carton weight validation
fix reconciliation for multi-part products
```
