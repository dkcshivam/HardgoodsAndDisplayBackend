# Deploying DKC Packing

Both repos, on one Linux server with Docker. Each has a
`docker-compose.prod.yml` beside its development `docker-compose.yml`; the
development files are not for production (Django's dev server, DEBUG on,
code mounted from disk).

## What runs

| Service | Repo | What it is |
|---|---|---|
| `db` | backend | Postgres 17. Data on the `pgdata` volume. Not reachable from outside Docker. |
| `backend` | backend | Django under gunicorn, DEBUG off. Runs migrations on start. Serves `/api` and `/admin`, and `/media` only when images are kept on disk. Port 8000 on `127.0.0.1` only. |
| `frontend` | frontend | The compiled Next.js app. Forwards `/api` to `backend` over Docker's network, so the browser only ever talks to this. Port 3000 on `127.0.0.1` only. |
| `caddy` | frontend | HTTPS on ports 80 and 443, with a certificate it fetches and renews itself. Optional: `--profile https`. |

Product images live in an S3 bucket, public-read, uploaded by Django. The
nightly database backup goes to a second, private bucket.

## 1. AWS

**Media bucket** — `dkc-packing-media` (bucket names are global; add a
suffix if it is taken), region `ap-south-1`:

- Object Ownership: *Bucket owner enforced* (the default).
- Block Public Access: turn off the two *bucket policy* settings; the two
  *ACL* settings can stay on.
- Bucket policy — anyone may read images, nothing else:

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "PublicReadImages",
    "Effect": "Allow",
    "Principal": "*",
    "Action": "s3:GetObject",
    "Resource": "arn:aws:s3:::dkc-packing-media/media/*"
  }]
}
```

**Backup bucket** — `dkc-packing-backups`, same region, every Block Public
Access setting left on. A lifecycle rule expiring `database/` after 30 days
keeps a month of nightly dumps.

**IAM user** — `dkc-packing-app`, no console access, with only this policy.
Its access key and secret go in the backend `.env` below.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
      "Resource": [
        "arn:aws:s3:::dkc-packing-media/media/*",
        "arn:aws:s3:::dkc-packing-backups/database/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": "s3:ListBucket",
      "Resource": ["arn:aws:s3:::dkc-packing-media", "arn:aws:s3:::dkc-packing-backups"]
    }
  ]
}
```

## 2. Settings

Create `.env` in the backend folder, beside `docker-compose.prod.yml`. It
holds secrets: never commit it.

```bash
# Required
DJANGO_SECRET_KEY=        # python3 -c "import secrets; print(secrets.token_urlsafe(50))"
DJANGO_ALLOWED_HOSTS=packing.dkcexport.co.in,backend
POSTGRES_PASSWORD=        # a long random password

# Images on S3, and the nightly backup
AWS_STORAGE_BUCKET_NAME=dkc-packing-media
AWS_BACKUP_BUCKET_NAME=dkc-packing-backups
AWS_REGION=ap-south-1
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=

# Optional
DJANGO_LOG_LEVEL=INFO     # default ERROR; INFO also logs every 4xx
BACKEND_PORT=8000
```

`DJANGO_ALLOWED_HOSTS` is every hostname people type, plus `backend`. A
missing required value stops `docker compose` with a message naming it.
Leave `AWS_STORAGE_BUCKET_NAME` out and images stay on the `media` volume.

With Caddy, the frontend folder needs a `.env` of one line — the address
people will type. Its DNS must already point at this server:

```bash
SITE_ADDRESS=packing.dkcexport.co.in
```

## 3. Start

```bash
cd HardgoodsAndDisplayBackend
docker compose -f docker-compose.prod.yml up -d --build

cd ../HardgoodsAndDisplayFrontend
docker compose -f docker-compose.prod.yml --profile https up -d --build
```

The backend first: the frontend joins its network. Leave out
`--profile https` where something else already serves HTTPS on this server
(its own nginx, a Cloudflare tunnel) and point that at `http://localhost:3000`.

## 4. Admin

```bash
docker compose -f docker-compose.prod.yml exec backend python manage.py createsuperuser
```

Open http://127.0.0.1:8000/admin on the server itself. From another machine,
forward the port first: `ssh -L 8000:127.0.0.1:8000 <server>`.

## Bringing existing data

**Database.** Make the dump inside the old database container and copy it
out — a binary file piped through PowerShell's `>` is corrupted on the way.

```bash
# On the old machine
docker exec dkc-packing-backend-db-1 pg_dump -U postgres -Fc -f /tmp/move.dump dkc_packing
docker cp dkc-packing-backend-db-1:/tmp/move.dump move.dump

# On the server, in the backend folder: the database alone first
docker compose -f docker-compose.prod.yml up -d db
docker compose -f docker-compose.prod.yml cp move.dump db:/tmp/move.dump
docker compose -f docker-compose.prod.yml exec db pg_restore -U postgres --clean --if-exists --no-owner -d dkc_packing /tmp/move.dump
docker compose -f docker-compose.prod.yml up -d --build
```

**Images.** Files, not database rows. Bring the old `media/` folder over
(`tar -czf media.tar.gz media`, copy, `tar -xzf media.tar.gz`), then put every
file in the bucket at the path the database knows it by. Re-running skips
what is already there.

```bash
docker compose -f docker-compose.prod.yml run --rm -v "$PWD/media:/source:ro" \
  backend python manage.py copy_media_to_storage --source /source
```

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

Nightly, from the server's cron (`crontab -e`), into the backup bucket:

```bash
30 2 * * * cd /home/ubuntu/HardgoodsAndDisplayBackend && docker compose -f docker-compose.prod.yml exec -T backend python manage.py backup_database >> /home/ubuntu/backup.log 2>&1
```

Run the same command by hand once to see it work. Images need no backup of
their own: S3 keeps them, and every one is also named in the database dump.

To restore, download a dump from the bucket and load it the way existing
data is brought in above.

## Logs

```bash
docker compose -f docker-compose.prod.yml logs -f backend
```

Every request, and the full error for anything that fails.

## Known limits

- **No login.** Anyone who can reach the site can read and change everything.
  Decided on 2026-09-25 to add one later.
- **Images are public.** Anyone with an image's address can open it. Only
  product photos belong in the media bucket.
- **`manage.py check --deploy` still warns about HTTPS.** Caddy (or the
  tunnel) already turns every http request into https before Django sees it;
  HSTS, which makes browsers skip http altogether, is not switched on yet.
