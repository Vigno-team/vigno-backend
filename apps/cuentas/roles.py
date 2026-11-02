"""Rol de una cuenta (E1C-64). Lo usan el login, /auth/yo y los permisos por rol de E1C-94."""

ROLES = ("administrador", "editor", "lector")


def rol_de(user):
    """El superusuario es administrador; el resto, según su grupo. Sin grupo de rol: None.

    Los grupos y los permisos por rol los crea E1C-94; aquí solo se leen.
    """
    if user.is_superuser:
        return "administrador"
    grupos = set(user.groups.values_list("name", flat=True))
    return next((r for r in ROLES if r in grupos), None)
