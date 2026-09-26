# DKC Packing — Backend

Django 5.2 + DRF + PostgreSQL. The API and the packing engine.

The frontend is a separate repo: `HardgoodsAndDisplayFrontend`.
**Start this one first** — the frontend is useless without it.

## Run it

Needs Docker Desktop running.

```bash
docker compose up -d
```

First run only, to get sample data and a login:

```bash
docker compose exec backend python manage.py seed_demo
docker compose exec backend python manage.py createsuperuser
```

- API — http://localhost:8000/api
- Admin — http://localhost:8000/admin

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
| `apps/masters/` | Categories and merchants |
| `apps/catalog/` | Products and their parts — the packing recipes |
| `apps/orders/` | Orders, cartons, `services.py` (the packing engine) and `exports.py` (the packing list) |
| `config/` | Settings and URL routing |
| `ARCHITECTURE.md` | **The spec.** Read this before changing behaviour. |
| `DEPLOY.md` | Running both repos in production. |
