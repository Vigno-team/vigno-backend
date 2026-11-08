"""Configuracion para el despliegue."""

from decouple import Csv, config
from django.core.exceptions import ImproperlyConfigured

from .base import *  # noqa: F401,F403
from .base import SECRET_KEY

DEBUG = False

# Los tokens del login (E1C-64) se firman con SECRET_KEY: con una clave corta o la de ejemplo
# cualquiera podría fabricar tokens válidos. Mejor que el despliegue no arranque.
if len(SECRET_KEY) < 50 or SECRET_KEY.startswith("REEMPLAZAR"):
    raise ImproperlyConfigured(
        "SECRET_KEY debe tener al menos 50 caracteres aleatorios. Generar con: "
        'python -c "import secrets; print(secrets.token_urlsafe(50))"'
    )

SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = config("SECURE_HSTS_SECONDS", default=3600, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_SECURE = config("SESSION_COOKIE_SECURE", default=True, cast=bool)
CSRF_COOKIE_SECURE = config("CSRF_COOKIE_SECURE", default=True, cast=bool)

CSRF_TRUSTED_ORIGINS = config("CSRF_TRUSTED_ORIGINS", default="", cast=Csv())
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# El límite de intentos del login (E1C-64) cuenta en la base: los workers de gunicorn son
# procesos separados y con caché en memoria cada uno llevaría su propia cuenta.
# La tabla la crea deploy/backend.py con createcachetable.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.db.DatabaseCache",
        "LOCATION": "vigno_cache",
    }
}

ADMIN_HABILITADO = config("ADMIN_HABILITADO", default=False, cast=bool)
ADMIN_POR_DEFECTO = config("ADMIN_POR_DEFECTO", default=False, cast=bool)
DOCS_HABILITADOS = config("DOCS_HABILITADOS", default=False, cast=bool)
