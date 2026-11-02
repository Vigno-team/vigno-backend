"""Crea el primer administrador desde DJANGO_SUPERUSER_EMAIL y DJANGO_SUPERUSER_PASSWORD (E1C-64).

Lo corre el contenedor al levantar. No hay registro público: el resto de las cuentas las crea
un administrador.
"""

import os

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Crea el primer administrador desde DJANGO_SUPERUSER_EMAIL y DJANGO_SUPERUSER_PASSWORD."

    def handle(self, *args, **options):
        correo = os.environ.get("DJANGO_SUPERUSER_EMAIL", "").strip().lower()
        clave = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "")
        if not correo and not clave:
            self.stdout.write("Sin DJANGO_SUPERUSER_EMAIL: no se crea administrador inicial.")
            return
        if not correo or not clave:
            raise CommandError(
                "Faltan DJANGO_SUPERUSER_EMAIL o DJANGO_SUPERUSER_PASSWORD: van las dos o ninguna."
            )

        User = get_user_model()
        if User.objects.filter(email__iexact=correo).exists():
            # Nunca se pisa la clave de una cuenta que ya existe: quien la cambió no la
            # recuperaría al reiniciar el contenedor.
            self.stdout.write(f"El administrador {correo} ya existe; no se modifica.")
            return

        usuario = User(username=correo, email=correo, is_staff=True, is_superuser=True)
        try:
            validate_password(clave, usuario)
        except ValidationError as error:
            raise CommandError(
                "DJANGO_SUPERUSER_PASSWORD no cumple las reglas de clave: "
                + " ".join(error.messages)
            ) from error
        usuario.set_password(clave)
        usuario.save()
        self.stdout.write(self.style.SUCCESS(f"Administrador inicial {correo} creado."))
