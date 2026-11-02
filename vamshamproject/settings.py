"""
Django settings for Vamsham — family website + REST API for the app and dashboard.

Everything secret or environment-specific is read from environment variables.
A `.env` file next to manage.py is loaded automatically (see .env.example).
Without it, safe development defaults are used. NEVER deploy with DJANGO_DEBUG=1.
"""

import os
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path):
    """Read KEY=VALUE lines from .env (real environment variables win)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")


def env(name, default=None):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


# ── Security ─────────────────────────────────────────────────────────────────
DEBUG = env_bool("DJANGO_DEBUG", True)

# In production DJANGO_SECRET_KEY MUST be set. The fallback only works with DEBUG on.
SECRET_KEY = env("DJANGO_SECRET_KEY") or (
    "dev-only-insecure-key-change-me-before-going-live-0123456789" if DEBUG else None
)
if not SECRET_KEY:
    raise RuntimeError("Set the DJANGO_SECRET_KEY environment variable in production.")

ALLOWED_HOSTS = env_list(
    "DJANGO_ALLOWED_HOSTS",
    "localhost,127.0.0.1,10.0.2.2",
)
CSRF_TRUSTED_ORIGINS = env_list(
    "DJANGO_CSRF_TRUSTED_ORIGINS",
    "",
)

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(env("DJANGO_HSTS_SECONDS", "3600"))
    SECURE_CONTENT_TYPE_NOSNIFF = True

LOGIN_URL = "/admin/login/"

# ── Applications ─────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    "jazzmin",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "mptt",
    "rest_framework",
    "corsheaders",
    "app1",
    "family",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "vamshamproject.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
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

WSGI_APPLICATION = "vamshamproject.wsgi.application"

# ── Database ─────────────────────────────────────────────────────────────────
# SQLite by default. Set DB_ENGINE=postgres (plus DB_NAME/DB_USER/DB_PASSWORD/
# DB_HOST/DB_PORT) on the server.
if env("DB_ENGINE", "sqlite") == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": env("DB_NAME", "vamsham"),
            "USER": env("DB_USER", "vamsham"),
            "PASSWORD": env("DB_PASSWORD", ""),
            "HOST": env("DB_HOST", "localhost"),
            "PORT": env("DB_PORT", ""),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

# ── Static & media ───────────────────────────────────────────────────────────
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ── REST API ─────────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": (
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 30,
    "DEFAULT_THROTTLE_RATES": {
        "otp": env("OTP_THROTTLE", "30/hour"),
        "login": env("LOGIN_THROTTLE", "30/hour"),
        "anon": "120/hour",
    },
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=int(env("JWT_ACCESS_HOURS", "12"))),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=int(env("JWT_REFRESH_DAYS", "60"))),
    "ROTATE_REFRESH_TOKENS": True,
    "UPDATE_LAST_LOGIN": True,
}

# The mobile app does not need CORS. These origins are for the Expo web build
# (admin panel in the browser) during development and on your domain.
CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:8081,http://localhost:19006",
)

# ── OTP / SMS ────────────────────────────────────────────────────────────────
# SMS_BACKEND: "console" (prints code to the server log — development only)
#              or "msg91" (set MSG91_AUTH_KEY, MSG91_TEMPLATE_ID).
SMS_BACKEND = env("SMS_BACKEND", "console")
MSG91_AUTH_KEY = env("MSG91_AUTH_KEY", "")
MSG91_TEMPLATE_ID = env("MSG91_TEMPLATE_ID", "")
OTP_TTL_SECONDS = int(env("OTP_TTL_SECONDS", "300"))
OTP_MAX_ATTEMPTS = 5
# For store reviewers / testing only: a fixed phone + code that always works. Leave empty in production.
OTP_TEST_PHONE = env("OTP_TEST_PHONE", "")
OTP_TEST_CODE = env("OTP_TEST_CODE", "")

# ── Jazzmin admin theme (Ocean Bento colours via static/vamsham/admin.css) ──────────────────────────────────────────
JAZZMIN_SETTINGS = {
    "site_title": "Vamsham Admin",
    "site_header": "Vamsham",
    "site_brand": "Vamsham",
    "site_logo": "images/logo/admin-logo.png",
    "login_logo": "images/logo/admin-logo.png",
    "login_logo_dark": "images/logo/admin-logo.png",
    "site_logo_classes": "images/logo/admin-logo.png",
    "site_icon": "images/favicon/favicon.ico",
    "show_ui_builder": False,
    "show_recent": False,
    "welcome_sign": "Welcome to Vamsham",
    "copyright": "Vamsham Family Association",
    "topmenu_links": [
        {"name": "Open Vamsham dashboard", "url": "/dashboard/"},
        {"name": "Website", "url": "/", "new_window": True},
    ],
    "custom_css": "vamsham/admin.css",
}

JAZZMIN_UI_TWEAKS = {
    "navbar_small_text": False,
    "footer_small_text": False,
    "body_small_text": True,
    "brand_small_text": False,
    "brand_colour": False,
    "accent": "accent-primary",
    "navbar": "navbar-white navbar-light",
    "no_navbar_border": False,
    "navbar_fixed": False,
    "layout_boxed": False,
    "footer_fixed": False,
    "sidebar_fixed": False,
    "sidebar": "sidebar-dark-primary",  # recoloured to navy in vamsham/admin.css
    "sidebar_nav_small_text": False,
    "sidebar_disable_expand": False,
    "sidebar_nav_child_indent": True,
    "sidebar_nav_compact_style": False,
    "sidebar_nav_legacy_style": True,
    "sidebar_nav_flat_style": False,
    "theme": "flatly",
    "dark_mode_theme": None,
    "button_classes": {
        "primary": "btn-outline-primary",
        "secondary": "btn-outline-secondary",
        "info": "btn-info",
        "warning": "btn-warning",
        "danger": "btn-danger",
        "success": "btn-success",
    },
}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"api": {"handlers": ["console"], "level": "INFO"}},
}
