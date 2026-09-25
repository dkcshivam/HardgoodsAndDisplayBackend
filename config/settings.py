"""
Anything that differs between a laptop and the server lives in .env.
See .env.example for the full list.
"""

from pathlib import Path

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

SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-me")
DEBUG = env_bool("DJANGO_DEBUG", True)
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

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
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
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

# Local disk in development; needs an object store before deployment.
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

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
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
        "rest_framework.renderers.BrowsableAPIRenderer",
    ],
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
        "A-4, SHIV MARG,GREEN AVN. , CHURCH ROAD",
        "VASANT KUNJ , NEW DELHI 110070",
        "INDIA",
        "Tel- + 9111 26124358",
    ],
    # Exporter registration numbers (static)
    "exporter_ref_no": "IEC No 0506081460",
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
        ("STATEMENT TYPE = DEC", "0"),
        ("STATEMENT CODE = RD001", "0"),
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


