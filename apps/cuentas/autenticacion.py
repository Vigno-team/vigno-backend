"""Token JWT con la regla del cambio de clave obligatorio (E1C-138)."""

from drf_spectacular.contrib.rest_framework_simplejwt import SimpleJWTScheme
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework_simplejwt.authentication import JWTAuthentication

from apps.cuentas.models import debe_cambiar_clave


class CambioDeClaveRequerido(APIException):
    status_code = status.HTTP_403_FORBIDDEN
    default_detail = "Tienes que cambiar tu clave antes de seguir."
    default_code = "cambio_de_clave_requerido"

    def __init__(self):
        # El code va en el cuerpo para que el frontend sepa mostrar la pantalla de cambio.
        super().__init__({"detail": self.default_detail, "code": self.default_code})


class JWTConClaveAlDia(JWTAuthentication):
    """Como JWTAuthentication, pero una cuenta con cambio de clave pendiente solo llega a las
    vistas que declaran `permite_cambio_de_clave_pendiente = True` (las de /auth/).

    Va aquí y no en los permisos porque muchas vistas definen sus propios permisos (E1C-94):
    la autenticación corre en todas las que usan token.
    """

    def authenticate(self, request):
        resultado = super().authenticate(request)
        if resultado is None:
            return None
        vista = (getattr(request, "parser_context", None) or {}).get("view")
        if debe_cambiar_clave(resultado[0]) and not getattr(
            vista, "permite_cambio_de_clave_pendiente", False
        ):
            raise CambioDeClaveRequerido()
        return resultado


class EsquemaJWTConClaveAlDia(SimpleJWTScheme):
    # Mismo esquema Bearer (jwtAuth) en /api/docs: la extensión original no cubre subclases.
    target_class = "apps.cuentas.autenticacion.JWTConClaveAlDia"
