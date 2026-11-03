"""Fixtures compartidas por todos los tests."""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

CORREO_PRUEBA = "analista@vigno.cl"
CLAVE_PRUEBA = "Vendimia-segura-2026"


@pytest.fixture(autouse=True)
def entorno_de_tests(settings):
    # Los tests de datos leen sin token, igual que los compose (API_LECTURA_PUBLICA=True).
    # Los de apps/cuentas la apagan para probar que por defecto todo pide token.
    settings.API_LECTURA_PUBLICA = True
    # El límite de intentos cuenta en la caché: sin limpiarla se arrastra entre tests.
    cache.clear()


@pytest.fixture
def usuario(db, django_user_model):
    return django_user_model.objects.create_user(
        username=CORREO_PRUEBA, email=CORREO_PRUEBA, password=CLAVE_PRUEBA
    )


def cliente_de(cuenta) -> APIClient:
    cliente = APIClient()
    cliente.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(cuenta).access_token}")
    return cliente


@pytest.fixture
def cliente_con_token(usuario):
    """APIClient con un token de acceso real de la cuenta de prueba."""
    return cliente_de(usuario)
