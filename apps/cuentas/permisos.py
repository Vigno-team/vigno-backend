from django.conf import settings
from rest_framework.permissions import SAFE_METHODS, BasePermission


class LecturaPublicaOAutenticado(BasePermission):
    """Las lecturas del dashboard quedan sin token solo si API_LECTURA_PUBLICA está activa.

    Es provisorio hasta que el frontend mande el token (E1C-64). Las escrituras y las
    lecturas privadas (cargas, correcciones, la cuenta) siempre piden token.
    """

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS and settings.API_LECTURA_PUBLICA:
            return True
        return bool(request.user and request.user.is_authenticated)
