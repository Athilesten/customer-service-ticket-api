import os
import secrets
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = os.getenv("TICKET_DEBUG", "0") == "1"
SECRET_KEY = os.getenv("TICKET_SECRET_KEY") or secrets.token_urlsafe(48)
ALLOWED_HOSTS = os.getenv("TICKET_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
ROOT_URLCONF = "helpdesk.urls"
INSTALLED_APPS = ["tickets"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "tickets.http.RequestContext"]
WSGI_APPLICATION = "helpdesk.wsgi.application"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
USE_TZ = True
TIME_ZONE = "UTC"
DATA_UPLOAD_MAX_MEMORY_SIZE = 32 * 1024


def positive_integer(name, default):
    try:
        value = int(os.getenv(name, default))
        if value > 0:
            return value
    except ValueError:
        pass
    raise ImproperlyConfigured(f"{name} must be a positive integer")


SLA_WARNING_MINUTES = positive_integer("TICKET_SLA_WARNING_MINUTES", 60)
SLA_HOURS = {}
for priority, response, resolution in (
    ("urgent", 1, 4), ("high", 2, 8), ("normal", 4, 24), ("low", 8, 72),
):
    prefix = f"TICKET_SLA_{priority.upper()}"
    response_hours = positive_integer(f"{prefix}_RESPONSE_HOURS", response)
    resolution_hours = positive_integer(f"{prefix}_RESOLUTION_HOURS", resolution)
    if not response_hours <= resolution_hours <= 87600:
        raise ImproperlyConfigured(f"{prefix} must have response <= resolution <= 87600 hours")
    SLA_HOURS[priority] = (response_hours, resolution_hours)

backend = os.getenv("TICKET_DB_BACKEND", "sqlite")
if backend == "postgres":
    database = {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.getenv("TICKET_PG_DATABASE", "helpdesk"),
        "USER": os.getenv("TICKET_PG_USER", "helpdesk"),
        "PASSWORD": os.getenv("TICKET_PG_PASSWORD", ""),
        "HOST": os.getenv("TICKET_PG_HOST", "127.0.0.1"),
        "PORT": os.getenv("TICKET_PG_PORT", "5432"),
        "OPTIONS": {"sslmode": os.getenv("TICKET_PG_SSLMODE", "prefer")},
    }
elif backend == "sqlite":
    database = {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": os.getenv("TICKET_SQLITE_PATH", str(BASE_DIR / "helpdesk.sqlite3")),
        "OPTIONS": {"transaction_mode": "IMMEDIATE", "timeout": 5},
    }
else:
    raise ImproperlyConfigured("TICKET_DB_BACKEND must be sqlite or postgres")
DATABASES = {"default": database}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"service": {"format": "%(asctime)s %(levelname)s %(name)s %(message)s"}},
    "handlers": {"service": {"class": "logging.StreamHandler", "formatter": "service"}},
    "loggers": {
        "tickets": {"handlers": ["service"], "level": os.getenv("TICKET_LOG_LEVEL", "INFO"),
                    "propagate": False},
        "django.request": {"handlers": ["service"], "level": "CRITICAL", "propagate": False},
        "django.server": {"handlers": ["service"], "level": "CRITICAL", "propagate": False},
    },
}
