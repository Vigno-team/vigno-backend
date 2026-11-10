"""Bitácora de auditoría: quién hizo qué, sobre qué objeto, cuándo y desde qué IP.

Solo se agregan registros: editar o borrar uno lanza SoloAgregar, también por QuerySet. El
admin además los muestra en solo lectura (apps/auditoria/admin.py).
"""

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


class SoloAgregar(Exception):
    """La bitácora no se edita ni se borra."""


class RegistroAuditoriaQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise SoloAgregar("Los registros de auditoría no se editan.")

    def delete(self):
        raise SoloAgregar("Los registros de auditoría no se borran.")


class RegistroAuditoria(models.Model):
    class Accion(models.TextChoices):
        LOGIN_CORRECTO = "login_correcto", "Inicio de sesión correcto"
        LOGIN_FALLIDO = "login_fallido", "Inicio de sesión fallido"
        CARGA_EXCEL = "carga_excel", "Carga de Excel"
        CARGA_SELECCION = "carga_seleccion", "Selección de variables de una carga"
        CORRECCION = "correccion", "Corrección manual"
        REVERSION = "reversion", "Reversión de una corrección"
        ESTACION_ALTA = "estacion_alta", "Alta de estación"
        ESTACION_EDICION = "estacion_edicion", "Edición de estación"
        ESTACION_BAJA = "estacion_baja", "Baja de estación"
        USUARIO_ALTA = "usuario_alta", "Alta de usuario"
        USUARIO_EDICION = "usuario_edicion", "Edición de usuario"
        USUARIO_BAJA = "usuario_baja", "Baja de usuario"
        CLAVE_CAMBIADA = "clave_cambiada", "Cambio de clave"
        MARCA_EDICION = "marca_edicion", "Edición de textos y colores de la marca"
        LOGO_EDICION = "logo_edicion", "Cambio del logo"

    # PROTECT: una cuenta con historial no se borra, se desactiva (is_active=False).
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="registros_auditoria",
        help_text="Quién hizo la acción; vacío en un login fallido",
    )
    accion = models.CharField(max_length=30, choices=Accion.choices, db_index=True)
    tipo_objeto = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text="Modelo afectado, por ejemplo clima.Estacion",
    )
    id_objeto = models.CharField(max_length=50, blank=True, default="")
    valor_anterior = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    valor_nuevo = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    ip = models.GenericIPAddressField(null=True, blank=True)
    fecha = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = RegistroAuditoriaQuerySet.as_manager()

    class Meta:
        ordering = ["-fecha", "-pk"]
        verbose_name = "registro de auditoría"
        verbose_name_plural = "registros de auditoría"

    def __str__(self):
        quien = self.usuario.email if self.usuario_id else "anónimo"
        return f"{self.fecha:%Y-%m-%d %H:%M} | {quien} | {self.get_accion_display()}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise SoloAgregar("Los registros de auditoría no se editan.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise SoloAgregar("Los registros de auditoría no se borran.")
