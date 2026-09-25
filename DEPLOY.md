# Deploying DKC Packing

Both repos, on one machine with Docker. Each has a `docker-compose.prod.yml`
beside its development `docker-compose.yml`; the development files are not
for production (Django's dev server, DEBUG on, code mounted from disk).

## What runs

| Service | Repo | What it is |
|---|---|---|
| `db` | backend | Postgres 17. Data on the `pgdata` volume. Not reachable from outside Docker. |
| `backend` | backend | Django under gunicorn, DEBUG off. Runs migrations on start. Serves `/api`, `/media` (uploaded images, on the `media` volume) and `/admin`. Port 8000 on `127.0.0.1` only. |
| `frontend` | frontend | The compiled Next.js app on port 3000. Forwards `/api` and `/media` to `backend` over Docker's network, so the browser only ever talks to this. |

Only port 3000 faces the internet, and only through something that adds
HTTPS: a Cloudflare tunnel, or a reverse proxy such as Caddy or nginx.

## 1. Settings

Create `.env` in the backend folder, beside `docker-compose.prod.yml`. It
holds secrets: never commit it.

```bash
# Required
DJANGO_SECRET_KEY=        # python -c "import secrets; print(secrets.token_urlsafe(50))"
DJANGO_ALLOWED_HOSTS=packing.co.in,backend
POSTGRES_PASSWORD=        # a long random password

# Optional
DJANGO_SECURE_COOKIES=True    # once the admin is reached over https
DJANGO_LOG_LEVEL=INFO         # default ERROR; INFO also logs every 4xx
BACKEND_PORT=8000
```

`DJANGO_ALLOWED_HOSTS` is every hostname people type, plus `backend`.
A missing required value stops `docker compose` with a message naming it.

The frontend needs no `.env`. Its two settings are fixed in its
`docker-compose.prod.yml` and compiled in at build time.

## 2. Start

```bash
cd HardgoodsAndDisplayBackend
docker compose -f docker-compose.prod.yml up -d --build

cd ../HardgoodsAndDisplayFrontend
docker compose -f docker-compose.prod.yml up -d --build
```

The backend first: the frontend joins its network. Then point the tunnel or
proxy at `http://localhost:3000`.

## 3. Admin

```bash
docker compose -f docker-compose.prod.yml exec backend python manage.py createsuperuser
```

Open http://127.0.0.1:8000/admin on the server itself. From another machine,
forward the port first: `ssh -L 8000:127.0.0.1:8000 <server>`.

## Bringing existing data

Start only the database, load a dump into it, then start the rest:

```bash
# On the old machine
docker exec dkc-packing-backend-db-1 pg_dump -U postgres --no-owner --no-acl dkc_packing > dkc_packing.sql

# On the new one, in the backend folder
docker compose -f docker-compose.prod.yml up -d db
docker compose -f docker-compose.prod.yml exec -T db psql -U postgres -d dkc_packing < dkc_packing.sql
docker compose -f docker-compose.prod.yml up -d --build
```

Uploaded images are files, not database rows. Copy the old `media/` folder in,
then hand it to the app's user, or new uploads will fail:

```bash
docker compose -f docker-compose.prod.yml cp ./media/. backend:/app/media/
docker compose -f docker-compose.prod.yml exec -u root backend chown -R app /app/media
```

**Switching this PC from the development setup.** The production files use
the same project names, so `up` replaces the development containers and keeps
the same database volume. Two things to know:

- Postgres keeps the password the volume was created with. `POSTGRES_PASSWORD`
  must be that one, not a new one.
- Development kept images in the `media/` folder; production keeps them in a
  volume. Copy them in as above.

`docker compose up -d` with the development file switches back.

## Updating

```bash
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

In each repo, backend first. Migrations run when the backend starts.

## Building here, running elsewhere

`--build` builds the images on whatever machine runs them. They are named
`dkc-packing-backend:prod` and `dkc-packing-frontend:prod`, so a build made
here can be carried to a server instead:

```bash
docker save dkc-packing-backend:prod dkc-packing-frontend:prod | gzip > dkc-packing-prod.tar.gz

# On the server, beside both repos' compose files and the backend .env
gunzip -c dkc-packing-prod.tar.gz | docker load
docker compose -f docker-compose.prod.yml up -d    # no --build: uses the loaded images
```

## Backups

```bash
docker compose -f docker-compose.prod.yml exec -T db pg_dump -U postgres --no-owner --no-acl dkc_packing > backup.sql
docker compose -f docker-compose.prod.yml cp backend:/app/media ./media-backup
```

Restore the database the way existing data is brought in above.

## Logs

```bash
docker compose -f docker-compose.prod.yml logs -f backend
```

Every request, and the full error for anything that fails.

## Known limits

- **No login.** Anyone who can reach the site can read and change everything.
  Decided on 2026-09-25 to add one later.
- **Images come from Django.** Fine for a handful of users. If image traffic
  ever slows the API, serve `/media` from nginx or object storage instead.
- **HTTPS is the tunnel's or proxy's job.** That is why
  `manage.py check --deploy` still mentions HSTS and the SSL redirect.
