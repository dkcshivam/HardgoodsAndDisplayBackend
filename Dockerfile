FROM python:3.13-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.9.26 /uv /bin/uv

# UV_PROJECT_ENVIRONMENT points at the image interpreter because the compose
# bind mount over /app would otherwise hide a .venv installed there.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/usr/local \
    UV_LINK_MODE=copy \
    UV_NO_CACHE=1

WORKDIR /app

# pg_dump, for `manage.py backup_database`. Debian 13 ships version 17, the
# same as the database; an older one refuses to dump a newer server.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY . .


FROM base AS dev
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]


FROM base AS prod
# media/ is made here so the volume mounted over it starts out owned by app;
# an empty one Docker creates itself is root's, and uploads would fail.
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput \
    && mkdir -p /app/media \
    && useradd --create-home --uid 1000 app \
    && chown -R app /app
USER app
EXPOSE 8000
# Threads, because images are served from here too and a worker would
# otherwise sit on each download. The frontend's proxy reuses connections,
# and gunicorn's default 2 s keep-alive closed them under it often enough to
# surface as a 500 now and then; 75 s is nginx's default.
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --threads 4 --timeout 120 --keep-alive 75 --access-logfile -"]
