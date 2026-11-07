"""Rol de una cuenta (E1C-64) y su asignación (E1C-94).

Cada rol es un grupo de Django (los crea la migración cuentas/0002_grupos_de_rol) y una cuenta
tiene uno solo. El superusuario cuenta como administrador aunque no esté en el grupo.
"""

from django.contrib.auth.models import Group

ADMINISTRADOR = "administrador"
EDITOR = "editor"
LECTOR = "lector"
ROLES = (ADMINISTRADOR, EDITOR, LECTOR)


def rol_de(user):
    # El superusuario es administrador; el resto, según su grupo. Sin grupo de rol: None.
    if user.is_superuser:
        return ADMINISTRADOR
    grupos = set(user.groups.values_list("name", flat=True))
    return next((r for r in ROLES if r in grupos), None)


def asignar_rol(usuario, rol):
    """Deja a la cuenta con un solo rol: saca los otros grupos de rol y agrega el pedido.

    Usa get_or_create por si la base se vació después de migrar (tests con transaction=True).
    """
    if rol not in ROLES:
        raise ValueError(f"Rol desconocido: {rol}. Usa uno de: {', '.join(ROLES)}.")
    grupo, _ = Group.objects.get_or_create(name=rol)
    usuario.groups.remove(*Group.objects.filter(name__in=ROLES).exclude(pk=grupo.pk))
    usuario.groups.add(grupo)
