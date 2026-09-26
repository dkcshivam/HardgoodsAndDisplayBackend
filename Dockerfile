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

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

COPY . .


FROM base AS dev
EXPOSE 8000
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]


FROM base AS prod
RUN DJANGO_SECRET_KEY=build-only python manage.py collectstatic --noinput \
    && useradd --create-home --uid 1000 app \
    && chown -R app /app
USER app
EXPOSE 8000
# Threads, because a photo upload holds its worker while it is passed on to
# S3. The frontend's proxy reuses connections, and gunicorn's default 2 s
# keep-alive closed them under it often enough to surface as a 500 now and
# then; 75 s is nginx's default.
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3 --threads 4 --timeout 120 --keep-alive 75 --access-logfile -"]
