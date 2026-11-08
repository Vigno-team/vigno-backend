"""
Configuracion comun a todos los entornos.
Los valores especificos de cada entorno viven en development.py y production.py.
"""

from datetime import timedelta
from pathlib import Path

from corsheaders.defaults import default_headers
from decouple import Csv, config

from vigno.instancia import cargar_configuracion

BASE_DIR = Path(__file__).resolve().parent.parent.parent
INSTANCIA_CONFIG = BASE_DIR / (config("INSTANCIA_CONFIG", default="") or "config/instancia.json")
# Un checkout nuevo arranca con una organización genérica y sin estaciones.
# Una ruta explícita inválida siempre falla: no se sustituye silenciosamente.
_ruta_instancia = INSTANCIA_CONFIG
if not _ruta_instancia.exists() and not config("INSTANCIA_CONFIG", default=""):
    _ruta_instancia = BASE_DIR / "config/instancia.example.json"
INSTANCIA = cargar_configuracion(_ruta_instancia)

SECRET_KEY = config("SECRET_KEY")
DEBUG = config("DEBUG", default=False, cast=bool)
ADMIN_HABILITADO = config("ADMIN_HABILITADO", default=True, cast=bool)
# E1C-138: sin ningún administrador activo, crear_admin_inicial crea admin@sistema.local / admin
# con cambio de clave obligatorio. production.py lo apaga salvo que se pida: en un servidor
# expuesto, quien entre primero con esa clave pública se quedaría con la cuenta.
ADMIN_POR_DEFECTO = config("ADMIN_POR_DEFECTO", default=True, cast=bool)
DOCS_HABILITADOS = config("DOCS_HABILITADOS", default=True, cast=bool)
ALLOWED_HOSTS = config("ALLOWED_HOSTS", default="localhost,127.0.0.1", cast=Csv())

# --- Aplicaciones ---
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "corsheaders",
    "drf_spectacular",
    "rest_framework_simplejwt.token_blacklist",
]

LOCAL_APPS = [
    "apps.clima",
    "apps.ingesta",
    "apps.cuentas",
    "apps.auditoria",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "vigno.urls"

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

WSGI_APPLICATION = "vigno.wsgi.application"

# --- Base de datos ---
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("POSTGRES_DB"),
        "USER": config("POSTGRES_USER"),
        "PASSWORD": config("POSTGRES_PASSWORD"),
        "HOST": config("POSTGRES_HOST", default="db"),
        "PORT": config("POSTGRES_PORT", default="5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# --- Internacionalizacion ---
LANGUAGE_CODE = "es-cl"
TIME_ZONE = INSTANCIA["zona_horaria"]
USE_I18N = True
USE_TZ = True

# Parámetros compartidos por la ficha de temporada y el detalle de rachas.
UMBRAL_CALOR_C = config("UMBRAL_CALOR_C", default=35.0, cast=float)
MINIMO_DIAS_INCIDENCIA = config("MINIMO_DIAS_INCIDENCIA", default=5, cast=int)
UMBRAL_LLUVIA_INTENSA_MM = config("UMBRAL_LLUVIA_INTENSA_MM", default=10.0, cast=float)
FACTOR_MES_INUSUAL = config("FACTOR_MES_INUSUAL", default=2.0, cast=float)

# Credenciales para Copernicus Data Space (se mantienen fuera del repositorio).
CDSE_CLIENT_ID = config("CDSE_CLIENT_ID", default="")
CDSE_CLIENT_SECRET = config("CDSE_CLIENT_SECRET", default="")

# Lecturas del dashboard sin token (E1C-64). Solo mientras el frontend no mande el token:
# los compose de desarrollo y de la demo la dejan en True; por defecto todo pide token.
API_LECTURA_PUBLICA = config("API_LECTURA_PUBLICA", default=False, cast=bool)

# Carpeta donde quedan los datos listos para el frontend.
DATOS_DIR = BASE_DIR / config("DATOS_DIR", default="data/cliente")

# --- Archivos estaticos ---
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# --- Django REST Framework ---
REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 50,
    # E1C-64: todo pide token salvo health, login y refresco (y las lecturas con
    # API_LECTURA_PUBLICA). Ver apps/cuentas.
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # JWT más el cambio de clave obligatorio (E1C-138).
        "apps.cuentas.autenticacion.JWTConClaveAlDia",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_THROTTLE_RATES": {"login": "5/min", "cambiar_clave": "5/min"},
    # Detrás de nginx la IP real es la última de X-Forwarded-For. Sin proxy delante (por
    # ejemplo runserver expuesto directo) debe ser 0: si no, el cliente elige su propia IP
    # escribiendo esa cabecera y se salta el límite de intentos.
    "NUM_PROXIES": config("NUM_PROXIES", default=1, cast=int),
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=15),
    "REFRESH_TOKEN_LIFETIME": timedelta(hours=8),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": True,
    # El token lleva un hash de la clave: al cambiarla, los tokens anteriores dejan de servir.
    "CHECK_REVOKE_TOKEN": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

# Contador del límite de intentos. En memoria sirve con un solo proceso (runserver y tests);
# production.py usa la base para que los workers de gunicorn compartan el contador.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}

# --- Contrato de la API (lo consume el equipo de frontend) ---
SPECTACULAR_SETTINGS = {
    "TITLE": f"{INSTANCIA['organizacion']['nombre_corto']} API",
    "DESCRIPTION": (
        f"API de análisis climático y cosecha de {INSTANCIA['organizacion']['nombre']}."
    ),
    "VERSION": "0.1.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # El token que se pega en Authorize (/api/docs) no queda guardado en el navegador.
    "SWAGGER_UI_SETTINGS": {"persistAuthorization": False},
}

# --- CORS ---
CORS_ALLOWED_ORIGINS = config(
    "CORS_ALLOWED_ORIGINS",
    default="http://localhost:5173",
    cast=Csv(),
)
CORS_EXPOSE_HEADERS = ["ETag"]
# default_headers ya incluye authorization, que lleva el token (Bearer).
CORS_ALLOW_HEADERS = [*default_headers, "if-none-match"]
