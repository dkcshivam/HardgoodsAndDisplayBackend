# Deploying DKC Packing

Both repos, on one Linux server with Docker — in production, the EC2 host
behind `hardgoods-and-display.ai.dkcexportstna.in` (the app) and
`backend-hardgoods-and-display.ai.dkcexportstna.in` (the admin). Each repo has a
`docker-compose.prod.yml` beside its development `docker-compose.yml`; the
development files are not for production (Django's dev server, DEBUG on,
code mounted from disk).

## What runs

| Service | Repo | What it is |
|---|---|---|
| `db` | backend | Postgres 17. Data on the `pgdata` volume. Not reachable from outside Docker. |
| `backend` | backend | Django under gunicorn, DEBUG off. Runs migrations on start. Serves `/api` and `/admin`. Port 8000 on `127.0.0.1`, and the admin address through Traefik. |
| `frontend` | frontend | The compiled Next.js app. Forwards `/api` to `backend` over Docker's network, so the browser only ever talks to this. Port 3000 on `127.0.0.1`, and the app address through Traefik. |

HTTPS comes from the **Traefik already running on the EC2 host**: the
`docker-compose.traefik.yml` in each repo labels the containers so Traefik
routes the two addresses to them and fetches their certificates. On a server
with nothing on ports 80/443, the frontend's `caddy` profile does the same
job instead.

Product images live in a **private** S3 bucket. Django uploads them, and every
image URL the API returns is signed and expires (24 hours by default). The
nightly database backup goes to a private bucket too — the same one is fine.

## 1. AWS

**Bucket** — region `ap-south-1`, every Block Public Access setting left on,
no bucket policy needed. Images go under `media/`, backups under `database/`.
A lifecycle rule expiring `database/` after 30 days keeps a month of dumps.

**Access** — whichever of the two suits:

- *Access keys* of an IAM user (in the backend `.env`), or
- *an IAM role on the EC2 instance*, with no keys anywhere. Leave both key
  lines out of `.env`. The containers reach the role through the instance
  metadata service, which needs its hop limit raised from 1 to 2:
  EC2 → the instance → Actions → Instance settings → Modify instance
  metadata options → *Metadata response hop limit* = 2.

Either way, give it only this (replace `BUCKET`):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": ["arn:aws:s3:::BUCKET/media/*", "arn:aws:s3:::BUCKET/database/*"]
    },
    {
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": "arn:aws:s3:::BUCKET"
    }
  ]
}
```

A signed URL works only as long as the credentials that signed it: up to the
full 24 hours with keys, but a role's credentials rotate every few hours, so
with a role set `AWS_S3_URL_EXPIRE_SECONDS=3600`.

## 2. Traefik's names

The labels need three names from the running Traefik. On the server:

```bash
docker ps --format '{{.Names}}\t{{.Image}}' | grep -i traefik
docker inspect --format '{{json .Args}}' <traefik-container>
docker inspect --format '{{range $n, $_ := .NetworkSettings.Networks}}{{$n}} {{end}}' <traefik-container>
```

- `--entrypoints.<name>.address=:443` → `TRAEFIK_ENTRYPOINT` (usually `websecure`);
  the one on `:80` → `TRAEFIK_HTTP_ENTRYPOINT` (usually `web`).
- `--certificatesresolvers.<name>.acme…` → `TRAEFIK_CERT_RESOLVER`.
- The network the other apps share with Traefik → `TRAEFIK_NETWORK`.

The defaults are `websecure`, `web` and `letsencrypt`; only differences need
writing down.

## 3. Settings

`.env` in the backend folder. It holds secrets: never commit it.

```bash
# Required
DJANGO_SECRET_KEY=        # python3 -c "import secrets; print(secrets.token_urlsafe(50))"
DJANGO_ALLOWED_HOSTS=hardgoods-and-display.ai.dkcexportstna.in,backend-hardgoods-and-display.ai.dkcexportstna.in,backend
DJANGO_SECURE_COOKIES=True
POSTGRES_PASSWORD=        # a long random password

# Images and backups on S3
AWS_STORAGE_BUCKET_NAME=
AWS_BACKUP_BUCKET_NAME=   # may be the same bucket
AWS_REGION=ap-south-1
AWS_ACCESS_KEY_ID=        # leave both out with an instance role
AWS_SECRET_ACCESS_KEY=

# Traefik (section 2)
API_ADDRESS=backend-hardgoods-and-display.ai.dkcexportstna.in
TRAEFIK_NETWORK=
# TRAEFIK_ENTRYPOINT=websecure
# TRAEFIK_HTTP_ENTRYPOINT=web
# TRAEFIK_CERT_RESOLVER=letsencrypt

# Optional
# AWS_S3_URL_EXPIRE_SECONDS=86400
# DJANGO_LOG_LEVEL=INFO     # default ERROR; INFO also logs every 4xx
```

`.env` in the frontend folder:

```bash
SITE_ADDRESS=hardgoods-and-display.ai.dkcexportstna.in
TRAEFIK_NETWORK=          # the same as the backend's
```

A missing required value stops `docker compose` with a message naming it.

## 4. Start

```bash
cd HardgoodsAndDisplayBackend
docker compose -f docker-compose.prod.yml -f docker-compose.traefik.yml up -d --build

cd ../HardgoodsAndDisplayFrontend
docker compose -f docker-compose.prod.yml -f docker-compose.traefik.yml up -d --build
```

The backend first: the frontend joins its network. Every later `docker
compose` command names the same two files.

## 5. Admin

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.traefik.yml exec backend python manage.py createsuperuser
```

Then https://backend-hardgoods-and-display.ai.dkcexportstna.in/admin/.

## Bringing existing data

**Database.** Make the dump inside the old database container and copy it
out — a binary file piped through PowerShell's `>` is corrupted on the way.

```bash
# On the old machine
docker exec dkc-packing-backend-db-1 pg_dump -U postgres -Fc -f /tmp/move.dump dkc_packing
docker cp dkc-packing-backend-db-1:/tmp/move.dump move.dump

# On the server, in the backend folder: the database alone first
docker compose -f docker-compose.prod.yml -f docker-compose.traefik.yml up -d db
docker compose -f docker-compose.prod.yml -f docker-compose.traefik.yml cp move.dump db:/tmp/move.dump
docker compose -f docker-compose.prod.yml -f docker-compose.traefik.yml exec db pg_restore -U postgres --clean --if-exists --no-owner -d dkc_packing /tmp/move.dump
docker compose -f docker-compose.prod.yml -f docker-compose.traefik.yml up -d --build
```

**Images.** Already in the bucket if the old machine used it. Otherwise bring
its `media/` folder over and put every file in the bucket at the path the
database knows it by; re-running skips what is already there.

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.traefik.yml run --rm -v "$PWD/media:/source:ro" \
  backend python manage.py copy_media_to_storage --source /source
```

## Updating

```bash
git pull
docker compose -f docker-compose.prod.yml -f docker-compose.traefik.yml up -d --build
```

In each repo, backend first. Migrations run when the backend starts.

## Building here, running elsewhere

`--build` builds the images on whatever machine runs them. They are named
`dkc-packing-backend:prod` and `dkc-packing-frontend:prod`, so a build made
here can be carried to a server instead:

```bash
docker save dkc-packing-backend:prod dkc-packing-frontend:prod | gzip > dkc-packing-prod.tar.gz

# On the server
gunzip -c dkc-packing-prod.tar.gz | docker load
docker compose -f docker-compose.prod.yml -f docker-compose.traefik.yml up -d    # no --build
```

## Backups

Nightly, from the server's cron (`crontab -e`), into the backup bucket:

```bash
30 2 * * * cd /home/ubuntu/HardgoodsAndDisplayBackend && docker compose -f docker-compose.prod.yml -f docker-compose.traefik.yml exec -T backend python manage.py backup_database >> /home/ubuntu/backup.log 2>&1
```

Run the same command by hand once to see it work. Images need no backup of
their own: S3 keeps them, and every one is named in the database dump.

To restore, download a dump from the bucket and load it the way existing
data is brought in above.

## Logs

```bash
docker compose -f docker-compose.prod.yml -f docker-compose.traefik.yml logs -f backend
```

Every request, and the full error for anything that fails.

## Known limits

- **No login.** Anyone who can reach the site can read and change everything.
  Decided on 2026-09-25 to add one later.
- **Image links expire.** A page left open longer than the expiry shows broken
  images until it is reloaded. Each signed link is new, so browsers download
  an image again on every page load rather than from their cache.
- **`manage.py check --deploy` still warns about HTTPS.** Traefik turns every
  http request into https before Django sees it; HSTS, which makes browsers
  skip http altogether, is not switched on yet.
