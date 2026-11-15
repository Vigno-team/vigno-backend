"""Recuperar la clave por correo.

Es opcional: solo se ofrece con un servidor de correo configurado (EMAIL_HOST, ver
vigno/settings). Sin él, la clave la restablece un administrador desde /api/v1/usuarios.
"""

import hashlib
import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from rest_framework.throttling import ScopedRateThrottle

from apps.configuracion.models import ConfiguracionInstancia

logger = logging.getLogger(__name__)


def enlace_para(usuario) -> str:
    # Enlace a la pantalla "Restablecer clave" del frontend, con el uid y el token.
    parametros = urlencode(
        {
            "uid": urlsafe_base64_encode(force_bytes(usuario.pk)),
            "token": default_token_generator.make_token(usuario),
        }
    )
    return f"{settings.FRONTEND_URL}/restablecer-clave?{parametros}"


def duracion_del_enlace() -> str:
    # Cuánto dura el enlace, en palabras: "1 hora", "2 horas" o "30 minutos".
    segundos = settings.PASSWORD_RESET_TIMEOUT
    if segundos % 3600 == 0:
        horas = segundos // 3600
        return "1 hora" if horas == 1 else f"{horas} horas"
    minutos = max(segundos // 60, 1)
    return "1 minuto" if minutos == 1 else f"{minutos} minutos"


def enviar_enlace(usuario) -> bool:
    organizacion = ConfiguracionInstancia.actual().nombre_organizacion
    cuerpo = (
        "Hola:\n\n"
        f"Recibimos un pedido para restablecer tu clave en {organizacion}. "
        "Para elegir una nueva, abre este enlace:\n\n"
        f"{enlace_para(usuario)}\n\n"
        f"El enlace dura {duracion_del_enlace()} y sirve una sola vez.\n"
        "Si no lo pediste, ignora este correo: tu clave no cambia.\n"
    )
    try:
        send_mail(f"Restablecer tu clave en {organizacion}", cuerpo, None, [usuario.email])
    except OSError:
        # SMTPException hereda de OSError, igual que los errores de red. La respuesta sigue
        # siendo 202: un error aquí delataría que el correo tiene cuenta.
        logger.exception("No se pudo enviar el correo de recuperación a la cuenta %s", usuario.pk)
        return False
    return True


class LimitePorCorreo(ScopedRateThrottle):
    scope_attr = "throttle_scope_correo"

    def get_cache_key(self, request, view):
        datos = request.data if isinstance(request.data, dict) else {}
        correo = str(datos.get("email", "")).strip().lower()
        if not correo:
            return None  # sin correo no hay qué contar: el serializer responde 400
        # Un hash: el correo no queda a la vista en la caché y la clave siempre cabe en la
        # tabla de la caché del despliegue (255 caracteres).
        ident = hashlib.sha256(correo.encode()).hexdigest()
        return self.cache_format % {"scope": self.scope, "ident": ident}
