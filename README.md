# DKC Packing — Backend

Django 5.2 + DRF + PostgreSQL. The API and the packing engine.

The frontend is a separate repo: `HardgoodsAndDisplayFrontend`.
**Start this one first** — the frontend is useless without it.

## Run it

Needs Docker Desktop running.

```bash
docker compose up -d
```

First run only, to get sample data and logins:

```bash
docker compose exec backend python manage.py seed_demo
docker compose exec backend python manage.py seed_users        # the app's logins
docker compose exec backend python manage.py createsuperuser   # your own, for /admin
```

- API — http://localhost:8000/api
- Admin — http://localhost:8000/admin

`seed_users` makes one login per role, each with the password `demo-pass-123`.
Re-running it puts them back as they were.

| Username | Role |
|---|---|
| `demo-admin` | Admin — can also manage users |
| `demo-senior` | Senior Merchant |
| `demo-merchant` | Merchant |

Every API request needs a login; see ARCHITECTURE.md §9. The demo users cannot
open /admin — that takes a superuser, which is an admin in the app too.

Stop with `docker compose down`. Your data survives; it lives in a Docker volume.

Photos go to S3 even here: copy `.env.example` to `.env` and fill in the AWS
lines, or uploads fail.

## Everyday commands

```bash
docker compose logs -f backend                      # watch the server
docker compose exec backend python manage.py test   # run the tests
docker compose exec backend python manage.py seed_demo   # reset sample data
docker compose exec backend python manage.py makemigrations   # after a model change
```

Migrations run automatically every time the container starts.

## Production

`docker compose up -d` is the development setup: Django's dev server with
DEBUG on. Production runs in Coolify from each repo's own compose file, with
the database on Amazon RDS — see [DEPLOY.md](DEPLOY.md).

## What is where

| Path | What it holds |
|---|---|
| `apps/common/calc.py` | The maths. Source of truth for every weight and volume. |
| `apps/accounts/` | Roles, login and the users endpoint |
| `apps/masters/` | Categories and merchants |
| `apps/catalog/` | Products and their parts — the packing recipes |
| `apps/orders/` | Orders, cartons, `services.py` (the packing engine) and `exports.py` (the packing list) |
| `config/` | Settings and URL routing |
| `ARCHITECTURE.md` | **The spec.** Read this before changing behaviour. |
| `DEPLOY.md` | Running both repos in production. |
