"""Configuracion para desarrollo local."""

from .base import *  # noqa: F401,F403

DEBUG = True

INTERNAL_IPS = ["127.0.0.1"]

# En local se permite cualquier origen para no bloquear al equipo de frontend.
CORS_ALLOW_ALL_ORIGINS = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "console": {"class": "logging.StreamHandler"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
}
