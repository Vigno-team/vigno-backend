from django.conf import settings
from django.db import models


class Perfil(models.Model):
    """Datos de la cuenta que no caben en el User de Django (E1C-138)."""

    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfil"
    )
    debe_cambiar_clave = models.BooleanField(
        default=False,
        help_text="Mientras esté activo, la API solo deja cambiar la clave, ver la cuenta, "
        "refrescar y cerrar sesión.",
    )

    class Meta:
        verbose_name_plural = "Perfiles"

    def __str__(self):
        return f"Perfil de {self.usuario}"


def debe_cambiar_clave(usuario) -> bool:
    """False para anónimos y para las cuentas sin perfil (creadas antes de E1C-138)."""
    if not getattr(usuario, "is_authenticated", False):
        return False
    try:
        return usuario.perfil.debe_cambiar_clave
    except Perfil.DoesNotExist:
        return False
