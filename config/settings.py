"""
Anything that differs between a laptop and the server lives in .env.
See .env.example for the full list.
"""

from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def env_bool(key: str, default: bool = False) -> bool:
    return env(key, str(default)).lower() in {"1", "true", "yes", "on"}


def env_list(key: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(key, default).split(",") if item.strip()]


# ── Core ─────────────────────────────────────────────────────────────

DEV_SECRET_KEY = "dev-only-insecure-key-change-me"
SECRET_KEY = env("DJANGO_SECRET_KEY", DEV_SECRET_KEY)
# Off unless asked for: a server started without its environment should fail
# safe, not hand tracebacks and settings to whoever hits an error page.
DEBUG = env_bool("DJANGO_DEBUG", False)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

if not DEBUG and SECRET_KEY in {"", DEV_SECRET_KEY}:
    raise ImproperlyConfigured(
        "Set DJANGO_SECRET_KEY. The development key is public, and DEBUG is off."
    )

# Only the admin uses sessions — the app has no login. Turn these on when the
# admin is reached over https.
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", False)

# Behind a TLS-terminating proxy — a tunnel, or any real deployment — the
# request arrives as plain http, so image URLs would come back http:// and a
# browser on an https page would block them as mixed content. A direct
# localhost request sends no such header and is unaffected.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# That proxy also rewrites Host to the container name, so absolute image URLs
# came back on http://backend:8000 — a name only Docker can resolve. Trust the
# forwarded host so they are built on the origin the browser actually used.
USE_X_FORWARDED_HOST = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "corsheaders",
    "django_filters",
    "apps.masters",
    "apps.catalog",
    "apps.orders",
    "apps.display",
]

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",  # must sit above CommonMiddleware
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# ── Database ─────────────────────────────────────────────────────────

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "dkc_packing"),
        "USER": env("POSTGRES_USER", "postgres"),
        "PASSWORD": env("POSTGRES_PASSWORD", ""),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
    }
}


# ── Auth ─────────────────────────────────────────────────────────────

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ── Localisation ─────────────────────────────────────────────────────

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True


# ── Static and media ─────────────────────────────────────────────────

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Uploaded images. Naming a bucket moves them to S3; without one (development,
# tests) they stay on local disk, served by Django itself (see urls.py).
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

AWS_STORAGE_BUCKET_NAME = env("AWS_STORAGE_BUCKET_NAME")
USE_S3 = bool(AWS_STORAGE_BUCKET_NAME)

# Credentials are not settings: boto3 reads AWS_ACCESS_KEY_ID and
# AWS_SECRET_ACCESS_KEY from the environment, or a server role if it has one.
S3_MEDIA = {
    "bucket_name": AWS_STORAGE_BUCKET_NAME,
    "region_name": env("AWS_REGION", "ap-south-1"),
    "location": "media",
    # The bucket policy makes media/ public, so plain URLs: a signed one
    # would expire, and the frontend keeps image URLs around.
    "querystring_auth": False,
    # New buckets refuse per-object ACLs; the policy is what grants reads.
    "default_acl": None,
    # A second photo with the same file name keeps both, as on disk.
    "file_overwrite": False,
}
# An S3-compatible service instead of AWS, such as a local stand-in to test
# against. It answers on a plain hostname, not <bucket>.<host>.
if endpoint := env("AWS_S3_ENDPOINT_URL"):
    S3_MEDIA |= {"endpoint_url": endpoint, "addressing_style": "path"}

STORAGES = {
    "default": (
        {"BACKEND": "storages.backends.s3.S3Storage", "OPTIONS": S3_MEDIA}
        if USE_S3
        else {"BACKEND": "django.core.files.storage.FileSystemStorage"}
    ),
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

# Where `manage.py backup_database` puts its dumps: a private bucket, never
# the public media one.
AWS_BACKUP_BUCKET_NAME = env("AWS_BACKUP_BUCKET_NAME")

# Tests store uploads on local disk even where S3 is configured.
TEST_RUNNER = "config.test_runner.LocalStorageRunner"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ── REST framework ───────────────────────────────────────────────────

REST_FRAMEWORK = {
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.common.pagination.StandardPagination",
    "PAGE_SIZE": 50,
    # Without this every weight arrives in the frontend as "0.600" and needs parsing.
    "COERCE_DECIMAL_TO_STRING": False,
    # The browsable API is a development aid; in production it would put an
    # edit form for every record in front of anyone who opens an API URL.
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"]
    + (["rest_framework.renderers.BrowsableAPIRenderer"] if DEBUG else []),
}


# ── Logging ──────────────────────────────────────────────────────────

# Django prints request errors to the console only while DEBUG is on. With it
# off they would go to admin email, which is not set up, so a 500 in
# production would leave no trace in `docker logs`. Errors only by default:
# gunicorn's access log already records every request and its status.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": env("DJANGO_LOG_LEVEL", "ERROR"),
            "propagate": False,
        },
    },
}


# ── CORS ─────────────────────────────────────────────────────────────

CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
)
CORS_ALLOW_CREDENTIALS = True
CSRF_TRUSTED_ORIGINS = CORS_ALLOWED_ORIGINS


# ── Export documents (Packing List & Invoice) ─────────────────────────

EXPORT_DOCUMENT_HEADER = {
    # If True, highlights static fields with yellow fill.
    # Set to False for clean white production print.
    "highlight_static": False,
    # Exporter details (static)
    "exporter": [
        "DKC EXPORTS PVT. LTD.",
        "A-4, SHIV MARG,GREEN AVN., CHURCH ROAD",
        "VASANT KUNJ , NEW DELHI 110070",
        "INDIA",
        "Tel- + 91 11 26124358",
    ],
    # Importer-Exporter Code (static). The invoice captions it "IEC CODE",
    # the packing list "Exporter's Ref No"; both print "IEC No <code>".
    "iec_code": "0506081460",
    "gstin": "07AACCD0416A1ZJ",
    # Consignee details (static)
    "consignee": [
        "URBAN OUTFITTERS INC",
        "5000 SOUTH BROAD STREET",
        "PHILADELPHIA",
        "PA 19112-1495",
        "USA",
        "",
        "PH:-(215) 454-5500",
        "FAX:-(215) 454-4660",
    ],
    # Regulatory, tax and origin codes (static)
    "statutory_details": [
        ("State of Origin Code", "07"),
        ("District of Origin Code", "84"),
        ("SQC", "PCS"),
        ("Pref. Agreements", "GSTP"),
        ("GST Comp. Cess", "N/A"),
        # Complete statements on their own; the desk's invoice leaves the
        # value column beside them empty.
        ("STATEMENT TYPE = DEC", ""),
        ("STATEMENT CODE = RD001", ""),
    ],
    # Origin and transport defaults (static)
    "country_of_origin": "INDIA",
    "pre_carriage_by": "ROAD",
    # Terms of delivery, payment and shipping marks (static)
    "terms_and_marks": [
        ("TERM OF DELIVERY OF PAYMENT", "FOB"),
        ("PAYMENT BY", "LC"),
        ("SHIPPING MARK", "URBAN OUTFITTERS INC"),
        ("SHIPPING LINE", ""),
        ("CONTAINER NO", ""),
    ],
}
