# Deploying DKC Packing

Both repos, deployed by **Coolify** on the EC2 host behind
`hardgoods-and-display.ai.dkcexportstna.in` (the app) and
`backend-hardgoods-and-display.ai.dkcexportstna.in` (the admin). Each repo has a
`docker-compose.prod.yml` beside its development `docker-compose.yml`; the
development files are not for production (Django's dev server, DEBUG on,
code mounted from disk).

## What runs

| Piece | Where | What it is |
|---|---|---|
| Database | Amazon RDS | Postgres 17. RDS keeps its automated backups. |
| `backend` | this repo, in Coolify | Django under gunicorn, DEBUG off. Runs migrations on start. Serves `/api` and `/admin` on port 8000 — the admin's CSS and JS too, through WhiteNoise — published nowhere: only Coolify's proxy and the frontend reach it. |
| `frontend` | frontend repo, in Coolify | The compiled Next.js app. Forwards `/api` to the backend's address, so the browser only ever talks to this. |
| Images | Amazon S3 | A **private** bucket. Django uploads them, and every image URL the API returns is signed and expires (24 hours by default). |

Coolify's proxy gives each address its HTTPS certificate and restarts a
container that stops. Nothing in the backend container needs keeping: the
data is in RDS and the images in S3.

## 1. AWS

**Database** — RDS for PostgreSQL 17, in the same VPC as the Coolify server,
public access off, and a security group that lets in port 5432 from that
server only. Set *Initial database name* to `dkc_packing`: Django creates the
tables, not the database. Leave automated backups on — they are the only
backups there are.

**Bucket** — region `ap-south-1`, every Block Public Access setting left on,
no bucket policy needed. Images go under `media/`.

**Access** — whichever of the two suits:

- *Access keys* of an IAM user (in Coolify's environment variables), or
- *an IAM role on the EC2 instance*, with no keys anywhere. Leave both key
  variables unset. The containers reach the role through the instance
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
      "Resource": "arn:aws:s3:::BUCKET/media/*"
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

## 2. Settings

Coolify's environment variables for the backend resource. They hold secrets:
never put them in a committed file.

```bash
# Required
DJANGO_SECRET_KEY=        # python3 -c "import secrets; print(secrets.token_urlsafe(50))"
DJANGO_ALLOWED_HOSTS=hardgoods-and-display.ai.dkcexportstna.in,backend-hardgoods-and-display.ai.dkcexportstna.in
DJANGO_SECURE_COOKIES=True

# RDS
POSTGRES_HOST=            # the instance's endpoint, …rds.amazonaws.com
POSTGRES_PASSWORD=
# POSTGRES_PORT=5432
# POSTGRES_DB=dkc_packing
# POSTGRES_USER=postgres

# Images on S3
AWS_STORAGE_BUCKET_NAME=
AWS_REGION=ap-south-1
AWS_ACCESS_KEY_ID=        # leave both out with an instance role
AWS_SECRET_ACCESS_KEY=

# Optional
# AWS_S3_URL_EXPIRE_SECONDS=86400
# DJANGO_LOG_LEVEL=INFO     # default ERROR; INFO also logs every 4xx
```

A missing required value stops the deploy with a message naming it.

## 3. Coolify

1. A new resource from this repo, build pack **Docker Compose**, compose file
   `docker-compose.prod.yml`.
2. The environment variables above.
3. The domain of the `backend` service:
   `https://backend-hardgoods-and-display.ai.dkcexportstna.in:8000`. The
   `:8000` is the container port the proxy forwards to; the address itself
   stays on 443.
4. Deploy. Migrations run when the container starts.

Then the frontend, the same way from its own repo: build pack **Docker
Compose**, compose file `docker-compose.prod.yml`, one environment variable,

```bash
API_PROXY_TARGET=https://backend-hardgoods-and-display.ai.dkcexportstna.in
```

and the domain `https://hardgoods-and-display.ai.dkcexportstna.in:3000` on its
`frontend` service. The two are separate resources on separate networks in
Coolify, so the frontend reaches the API by its public address. The address
is compiled into the build: changing it needs a redeploy.

## 4. Admin

From the backend's *Terminal* tab in Coolify:

```bash
python manage.py createsuperuser
```

Then https://backend-hardgoods-and-display.ai.dkcexportstna.in/admin/.

## Bringing existing data

**Database.** Make the dump inside the old database container and copy it
out — a binary file piped through PowerShell's `>` is corrupted on the way.

```bash
# On the old machine
docker exec dkc-packing-backend-db-1 pg_dump -U postgres -Fc -f /tmp/move.dump dkc_packing
docker cp dkc-packing-backend-db-1:/tmp/move.dump move.dump
```

Then, on the Coolify server with the backend stopped, load it into RDS with a
throwaway Postgres 17 container, and deploy again afterwards:

```bash
docker run --rm -v "$PWD/move.dump:/move.dump:ro" -e PGPASSWORD='<password>' postgres:17-alpine \
  pg_restore -h <rds-endpoint> -U postgres --clean --if-exists --no-owner -d dkc_packing /move.dump
```

**Images.** Already in the bucket if the old machine used it. Otherwise, on
the machine that still has its `media/` folder, name the bucket in its `.env`
and put every file in the bucket at the path the database knows it by;
re-running skips what is already there.

```bash
docker compose exec backend python manage.py copy_media_to_storage --source /app/media
```

## Updating

Redeploy the backend in Coolify, or let its git webhook do it on push, then
the frontend. Migrations run when the backend starts.

## Backups

RDS takes them: automated backups for point-in-time restore, and manual
snapshots before anything risky. Restoring makes a new instance; point
`POSTGRES_HOST` at it and redeploy. Images need no backup of their own: S3
keeps them, and every one is named in the database.

## Logs

The backend's *Logs* tab in Coolify: every request, and the full error for
anything that fails.

## Known limits

- **No login.** Anyone who can reach the site can read and change everything.
  Decided on 2026-09-25 to add one later.
- **Image links expire.** A page left open longer than the expiry shows broken
  images until it is reloaded. Each signed link is new, so browsers download
  an image again on every page load rather than from their cache.
- **`manage.py check --deploy` still warns about HTTPS.** Coolify's proxy turns
  every http request into https before Django sees it; HSTS, which makes
  browsers skip http altogether, is not switched on yet.
