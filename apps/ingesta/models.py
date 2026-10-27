from django.db import models


class RegistroCarga(models.Model):
    ESTADO_OK = "OK"
    ESTADO_FALLIDA = "FALLIDA"
    ESTADO_CHOICES = [
        (ESTADO_OK, "Exitosa"),
        (ESTADO_FALLIDA, "Fallida"),
    ]

    fecha_carga = models.DateTimeField(
        auto_now_add=True, help_text="Fecha y hora en que se corrio el script"
    )
    archivo = models.CharField(max_length=255, help_text="Ruta o nombre del Excel origen")
    hash_archivo = models.CharField(
        max_length=64,
        null=True,
        blank=True,
        db_index=True,
        help_text="SHA-256 del archivo: el mismo archivo no se procesa dos veces",
    )
    estacion = models.CharField(max_length=100)
    formato_detectado = models.CharField(max_length=50, null=True, blank=True)
    temporada = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Temporada del archivo (ej: 2024)"
    )
    fecha_desde = models.DateField(null=True, blank=True)
    fecha_hasta = models.DateField(null=True, blank=True)

    filas_leidas = models.IntegerField(default=0)
    filas_vacias_ignoradas = models.PositiveIntegerField(default=0)
    filas_aceptadas = models.IntegerField(default=0)
    filas_rechazadas = models.IntegerField(default=0)

    detalle_rechazos = models.JSONField(
        null=True, blank=True, help_text="Lista de filas rechazadas: fila, valor original y motivo"
    )
    celdas_vacias_conservadas = models.JSONField(
        default=list,
        blank=True,
        help_text="Celdas vacías que no borraron un valor ya cargado: fila, fecha y variable",
    )
    columnas_descartadas = models.CharField(
        max_length=255, null=True, blank=True, help_text="Constancia del descarte de Abejas"
    )

    registros_insertados = models.IntegerField(default=0)
    registros_actualizados = models.IntegerField(
        default=0, help_text="Actualizados CON cambio de valor"
    )
    registros_sin_cambio = models.IntegerField(
        default=0, help_text="Ya existían con el mismo valor"
    )
    registros_omitidos = models.IntegerField(
        default=0, help_text="No se tocaron porque ya venían de una temporada más nueva"
    )

    estado = models.CharField(max_length=10, choices=ESTADO_CHOICES, default=ESTADO_OK)
    error = models.TextField(blank=True, default="")

    usuario = models.CharField(max_length=100, default="Sistema (Terminal)")

    class Meta:
        verbose_name_plural = "Registros de Carga"

    def __str__(self):
        return (
            f"{self.fecha_carga.strftime('%Y-%m-%d %H:%M')} | {self.estacion} "
            f"({self.registros_insertados} nuevos) [{self.estado}]"
        )
