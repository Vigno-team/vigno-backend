"""Clave de API (cabecera X-Api-Key) para los endpoints que escriben datos.

Compartida con la carga de Excel por API. Si esa tarea ya define su propia clase,
basta con importarla en `apps/clima/views.py` en lugar de esta.
"""

import hmac

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.permissions import SAFE_METHODS

CABECERA = "X-Api-Key"


class UsuarioApi(AnonymousUser):
    """Quien presenta la clave correcta; no es una cuenta de Django."""

    @property
    def is_authenticated(self):
        return True


class ApiKeyAuthentication(BaseAuthentication):
    """Solo se exige al escribir: las lecturas siguen públicas aunque lleguen con otra clave."""

    def authenticate(self, request):
        if request.method in SAFE_METHODS:
            return None
        recibida = request.headers.get(CABECERA, "")
        if not recibida:
            return None  # el permiso lo rechaza con 401
        esperada = getattr(settings, "INGESTA_API_KEY", "")
        # Sin clave configurada nada entra: es preferible a dejar la escritura abierta.
        if not esperada or not hmac.compare_digest(recibida.encode(), esperada.encode()):
            raise AuthenticationFailed("Clave de API inválida.")
        return (UsuarioApi(), None)

    def authenticate_header(self, request):
        # Hace que DRF responda 401 (y no 403) cuando falta la clave.
        return CABECERA
