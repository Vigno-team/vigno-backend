"""Escribir en la bitácora de auditoría.

La usan la API (login, cargas, correcciones, estaciones), el admin de Django y,
el CRUD de usuarios y estaciones. Siempre se llama dentro del mismo transaction.atomic() que el
cambio: si el cambio se deshace, el registro también.
"""

import ipaddress

from rest_framework.throttling import BaseThrottle

from apps.auditoria.models import RegistroAuditoria
from apps.cuentas.roles import rol_de

Accion = RegistroAuditoria.Accion

CAMPOS_ESTACION = ("nombre", "codigo", "subzona", "propietario", "latitud", "longitud", "activa")
# Nunca la clave: ni siquiera su hash entra en la bitácora.
CAMPOS_USUARIO = (
    "username",
    "email",
    "first_name",
    "last_name",
    "is_active",
    "is_staff",
    "is_superuser",
)


def ip_de(request) -> str | None:
    """IP del cliente, con la misma regla que el límite de intentos del login (NUM_PROXIES).

    Detrás de nginx sale de X-Forwarded-For; sin proxy, de REMOTE_ADDR. Si no es una IP válida
    (una cabecera inventada, por ejemplo) queda vacía en vez de romper el cambio.
    """
    if request is None:
        return None
    try:
        return str(ipaddress.ip_address(BaseThrottle().get_ident(request).strip()))
    except (AttributeError, ValueError):
        return None


def instantanea_estacion(estacion) -> dict:
    return {campo: getattr(estacion, campo) for campo in CAMPOS_ESTACION}


def instantanea_usuario(usuario) -> dict:
    return {
        "id": usuario.pk,
        **{campo: getattr(usuario, campo) for campo in CAMPOS_USUARIO},
        "rol": rol_de(usuario),
    }


def registrar(
    accion,
    *,
    request=None,
    usuario=None,
    objeto=None,
    tipo_objeto="",
    id_objeto="",
    anterior=None,
    nuevo=None,
) -> RegistroAuditoria:
    """Agrega un registro a la bitácora.

    - usuario: quién hizo la acción. Si no se indica sale de request.user; un anónimo queda vacío.
    - objeto: la instancia afectada; de ella salen tipo_objeto ("clima.Estacion") e id_objeto.
      Si ya no existe (una baja), se pasan tipo_objeto e id_objeto a mano.
    - anterior / nuevo: lo que había y lo que quedó, como dict serializable a JSON.
    """
    if usuario is None and request is not None:
        usuario = getattr(request, "user", None)
    if usuario is not None and not usuario.is_authenticated:
        usuario = None
    if objeto is not None:
        tipo_objeto = tipo_objeto or objeto._meta.label
        id_objeto = id_objeto or objeto.pk
    return RegistroAuditoria.objects.create(
        usuario=usuario,
        accion=accion,
        tipo_objeto=tipo_objeto,
        id_objeto=str(id_objeto),
        valor_anterior=anterior,
        valor_nuevo=nuevo,
        ip=ip_de(request),
    )
