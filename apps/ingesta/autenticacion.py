"""Clave compartida por las escrituras de ingesta, estaciones y correcciones."""

import hmac

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from drf_spectacular.extensions import OpenApiAuthenticationExtension
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
    """Las lecturas públicas se pueden desactivar para bitácoras con autor y motivo."""

    lecturas_publicas = True

    def authenticate(self, request):
        if self.lecturas_publicas and request.method in SAFE_METHODS:
            return None
        recibida = request.headers.get(CABECERA, "")
        if not recibida:
            return None
        esperada = getattr(settings, "INGESTA_API_KEY", "")
        if not esperada or not hmac.compare_digest(recibida.encode(), esperada.encode()):
            raise AuthenticationFailed("Clave de API inválida.")
        return (UsuarioApi(), None)

    def authenticate_header(self, request):
        return CABECERA


class ApiKeyPrivadaAuthentication(ApiKeyAuthentication):
    lecturas_publicas = False


class EsquemaApiKey(OpenApiAuthenticationExtension):
    target_class = "apps.ingesta.autenticacion.ApiKeyAuthentication"
    match_subclasses = True
    name = "ingestaApiKey"

    def get_security_definition(self, auto_schema):
        return {"type": "apiKey", "in": "header", "name": CABECERA}
