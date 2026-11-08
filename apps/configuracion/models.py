"""Marca de la instancia: nombres, logo, colores, tipografía y pie.

Hay una sola fila (pk=1). Se crea al primer uso con los nombres de config/instancia.json
; desde ahí manda la base y el administrador la cambia por la API, sin desplegar.
"""

from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

# \Z y no $: $ acepta un salto de línea al final ("#FFFFFF\n").
COLOR_HEX = RegexValidator(r"^#[0-9A-Fa-f]{6}\Z", "Usa el formato #RRGGBB, por ejemplo #1F4E79.")


def ruta_logo(instancia, nombre):
    # Un nombre nuevo en cada subida: la URL cambia y ningún navegador muestra el logo viejo.
    # La extensión la pone la validación según el formato real, no la que trae el cliente.
    return f"marca/logo-{uuid4().hex}{Path(nombre).suffix.lower()}"


class ConfiguracionInstancia(models.Model):
    UNICA = 1

    nombre_organizacion = models.CharField(max_length=100)
    nombre_sistema = models.CharField(max_length=100)
    logo = models.ImageField(upload_to=ruta_logo, blank=True)
    color_primario = models.CharField(max_length=7, default="#1F4E79", validators=[COLOR_HEX])
    color_secundario = models.CharField(max_length=7, default="#4A7C59", validators=[COLOR_HEX])
    color_acento = models.CharField(max_length=7, default="#C9A227", validators=[COLOR_HEX])
    color_fondo = models.CharField(max_length=7, default="#FFFFFF", validators=[COLOR_HEX])
    tipografia = models.CharField(
        max_length=100,
        default="system-ui",
        help_text="Familia CSS que el frontend aplica, por ejemplo Inter",
    )
    texto_pie = models.CharField(max_length=200, blank=True, default="")
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "configuración de la instancia"
        verbose_name_plural = "configuración de la instancia"
        constraints = [
            # La base misma impide una segunda fila, aunque alguien salte save().
            models.CheckConstraint(condition=models.Q(id=1), name="configuracion_instancia_unica"),
        ]

    def __str__(self):
        return f"Marca de {self.nombre_organizacion}"

    def save(self, *args, **kwargs):
        self.pk = self.UNICA
        super().save(*args, **kwargs)

    @classmethod
    def actual(cls):
        """La única fila. Si aún no existe, la crea con los nombres de instancia.json."""
        organizacion = settings.INSTANCIA["organizacion"]
        configuracion, _ = cls.objects.get_or_create(
            pk=cls.UNICA,
            defaults={
                "nombre_organizacion": organizacion["nombre"],
                "nombre_sistema": organizacion["nombre_corto"],
            },
        )
        return configuracion
