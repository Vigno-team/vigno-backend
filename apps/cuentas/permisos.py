"""Permisos por rol. Sin token la respuesta es 401; con token y sin el rol, 403."""

from django.conf import settings
from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.cuentas.roles import ADMINISTRADOR, EDITOR, ROLES, rol_de


def _rol(request):
    usuario = getattr(request, "user", None)
    if not (usuario and usuario.is_authenticated):
        return None
    return rol_de(usuario)


class EsAdministrador(BasePermission):
    """Solo administradores (y superusuarios): usuarios, configuración y la bitácora."""

    message = "Solo un administrador puede hacer esto."

    def has_permission(self, request, view):
        return _rol(request) == ADMINISTRADOR


class PuedeEditar(BasePermission):
    """Administrador o editor: subir Excel, corregir, revertir y crear estaciones."""

    message = "Tu rol solo permite leer."

    def has_permission(self, request, view):
        return _rol(request) in (ADMINISTRADOR, EDITOR)


class PuedeLeer(BasePermission):
    """Cualquier rol.

    Las vistas del dashboard (`lectura_publica = True`) además abren sus lecturas sin token
    mientras API_LECTURA_PUBLICA esté activa. Cargas, correcciones y la bitácora no
    la declaran: nunca son públicas.
    """

    message = "Tu cuenta no tiene un rol asignado."

    def has_permission(self, request, view):
        if (
            request.method in SAFE_METHODS
            and getattr(view, "lectura_publica", False)
            and settings.API_LECTURA_PUBLICA
        ):
            return True
        return _rol(request) in ROLES


class LeerOEditar:
    """Mezcla para vistas con GET y POST: leer pide PuedeLeer y escribir, PuedeEditar."""

    def get_permissions(self):
        metodo = getattr(getattr(self, "request", None), "method", None)
        if metodo is None or metodo in SAFE_METHODS:
            return [PuedeLeer()]
        return [PuedeEditar()]
