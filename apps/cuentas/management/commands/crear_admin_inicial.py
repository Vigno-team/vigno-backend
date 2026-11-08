"""Deja un administrador al levantar el sistema (E1C-64, E1C-138).

Lo corre el contenedor al arrancar. No hay registro público: el resto de las cuentas las crea
un administrador.

1. Si ya hay un administrador activo, no crea ni modifica nada.
2. Si están DJANGO_SUPERUSER_EMAIL y DJANGO_SUPERUSER_PASSWORD, crea esa cuenta.
3. Si no, y ADMIN_POR_DEFECTO está activo, crea admin@sistema.local / admin con cambio de clave
   obligatorio en el primer ingreso.
"""

import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from apps.auditoria.registro import Accion, instantanea_usuario, registrar
from apps.cuentas.models import Perfil
from apps.cuentas.roles import ADMINISTRADOR

# Documentados en el README. La clave no cumple las reglas a propósito: es pública y la cuenta
# no puede usar la API hasta cambiarla.
CORREO_POR_DEFECTO = "admin@sistema.local"
CLAVE_POR_DEFECTO = "admin"


def hay_administrador_activo() -> bool:
    return (
        get_user_model()
        .objects.filter(is_active=True)
        .filter(Q(is_superuser=True) | Q(groups__name=ADMINISTRADOR))
        .exists()
    )


class Command(BaseCommand):
    help = "Crea el primer administrador si no hay ninguno activo."

    def handle(self, *args, **options):
        correo = os.environ.get("DJANGO_SUPERUSER_EMAIL", "").strip().lower()
        clave = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "")
        if bool(correo) != bool(clave):
            raise CommandError(
                "Faltan DJANGO_SUPERUSER_EMAIL o DJANGO_SUPERUSER_PASSWORD: van las dos o ninguna."
            )

        if hay_administrador_activo():
            self.stdout.write("Ya existe un administrador activo; no se crea ni se modifica nada.")
            return

        if correo:
            self.crear(correo, clave, debe_cambiar=False, origen="variables de entorno")
        elif settings.ADMIN_POR_DEFECTO:
            self.crear(
                CORREO_POR_DEFECTO, CLAVE_POR_DEFECTO, debe_cambiar=True, origen="por defecto"
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "No hay administrador. Define DJANGO_SUPERUSER_EMAIL y "
                    "DJANGO_SUPERUSER_PASSWORD, o ADMIN_POR_DEFECTO=True."
                )
            )

    def crear(self, correo, clave, debe_cambiar, origen):
        User = get_user_model()
        if User.objects.filter(email__iexact=correo).exists():
            # Nunca se convierte en administrador ni se cambia la clave de una cuenta que ya existe.
            self.stdout.write(
                self.style.WARNING(
                    f"La cuenta {correo} ya existe y no es administrador activo; no se modifica."
                )
            )
            return

        usuario = User(username=correo, email=correo, is_staff=True, is_superuser=True)
        if not debe_cambiar:
            try:
                validate_password(clave, usuario)
            except ValidationError as error:
                raise CommandError(
                    "DJANGO_SUPERUSER_PASSWORD no cumple las reglas de clave: "
                    + " ".join(error.messages)
                ) from error
        usuario.set_password(clave)
        with transaction.atomic():
            usuario.save()
            Perfil.objects.create(usuario=usuario, debe_cambiar_clave=debe_cambiar)
            # Sin usuario: lo hizo el sistema al arrancar. Nunca la clave.
            registrar(
                Accion.USUARIO_ALTA,
                objeto=usuario,
                nuevo={
                    **instantanea_usuario(usuario),
                    "debe_cambiar_clave": debe_cambiar,
                    "origen": f"crear_admin_inicial ({origen})",
                },
            )
        if debe_cambiar:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Administrador por defecto {correo} creado: hay que cambiar la clave en el "
                    "primer ingreso."
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS(f"Administrador inicial {correo} creado."))
