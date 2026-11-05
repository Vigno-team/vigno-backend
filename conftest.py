"""Los tests históricos cargan explícitamente su instancia, no desde migraciones."""

from pathlib import Path

import pytest
from django.core.cache import cache
from django.core.management import call_command
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from apps.cuentas.roles import ADMINISTRADOR, EDITOR, LECTOR, asignar_rol
from vigno.instancia import cargar_configuracion

CARPETA = Path(__file__).parent / "config/instancias/casas-patronales"
CORREO_PRUEBA = "analista@vigno.cl"
CLAVE_PRUEBA = "Vendimia-segura-2026"


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("cargar_instancia", str(CARPETA), sin_activar=True, verbosity=0)


@pytest.fixture(autouse=True)
def instancia_historica(settings):
    settings.INSTANCIA = cargar_configuracion(CARPETA / "instancia.json")
    settings.TIME_ZONE = settings.INSTANCIA["zona_horaria"]


@pytest.fixture(autouse=True)
def entorno_de_tests(settings):
    # Los tests de datos leen sin token, igual que los compose (API_LECTURA_PUBLICA=True).
    # Los de apps/cuentas la apagan para probar que por defecto todo pide token.
    settings.API_LECTURA_PUBLICA = True
    # El límite de intentos cuenta en la caché: sin limpiarla se arrastra entre tests.
    cache.clear()


def crear_cuenta(django_user_model, correo, rol=None):
    """Cuenta con la clave de prueba y, si se indica, un rol (E1C-94)."""
    cuenta = django_user_model.objects.create_user(
        username=correo, email=correo, password=CLAVE_PRUEBA
    )
    if rol:
        asignar_rol(cuenta, rol)
    return cuenta


@pytest.fixture
def usuario(db, django_user_model):
    """La cuenta de prueba es editor: puede cargar, corregir y crear estaciones (E1C-94)."""
    return crear_cuenta(django_user_model, CORREO_PRUEBA, EDITOR)


def cliente_de(cuenta) -> APIClient:
    cliente = APIClient()
    cliente.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(cuenta).access_token}")
    return cliente


@pytest.fixture
def cliente_con_token(usuario):
    """APIClient con un token de acceso real de la cuenta de prueba (rol editor)."""
    return cliente_de(usuario)


@pytest.fixture
def cliente_lector(db, django_user_model):
    """Dirección: solo lee."""
    return cliente_de(crear_cuenta(django_user_model, "direccion@vigno.cl", LECTOR))


@pytest.fixture
def cliente_admin(db, django_user_model):
    """Administrador por grupo (no superusuario), para probar el camino del rol."""
    return cliente_de(crear_cuenta(django_user_model, "admin@vigno.cl", ADMINISTRADOR))
