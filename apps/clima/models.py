from django.db import models


class Estacion(models.Model):
    nombre = models.CharField(max_length=100, unique=True)

    class Meta:
        verbose_name_plural = "Estaciones"

    def __str__(self):
        return self.nombre


class MedicionHoraria(models.Model):
    FRECUENCIA_CHOICES = [
        ("D", "Diaria"),
        ("H", "Horaria"),
    ]

    estacion = models.ForeignKey(Estacion, on_delete=models.CASCADE, related_name="mediciones")
    timestamp = models.DateTimeField(help_text="Fecha de la medicion")
    variable = models.CharField(max_length=50, help_text="Nombre estandarizado de la variable")
    frecuencia = models.CharField(
        max_length=1,
        choices=FRECUENCIA_CHOICES,
        default="D",
        help_text="Resolución temporal del dato",
    )

    valor = models.FloatField(
        null=True,
        blank=True,
        help_text="Valor numerico de la medicion (nulo si no hay dato valido)",
    )
    motivo_nulo = models.CharField(
        max_length=255, null=True, blank=True, help_text="Razon por la cual el valor es nulo"
    )

    # Temporada del archivo del que vino el dato
    temporada = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Temporada del archivo de origen (ej: 2024)"
    )

    # FK para saber de qué archivo vino exactamente este dato
    carga = models.ForeignKey(
        "ingesta.RegistroCarga",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mediciones_generadas",
    )

    class Meta:
        db_table = "medicion_horaria"
        # Unicidad estricta para el manejo de conflictos
        unique_together = ("estacion", "timestamp", "variable", "frecuencia")
        indexes = [
            models.Index(fields=["estacion", "timestamp", "frecuencia"]),
            models.Index(fields=["variable"]),
        ]
        verbose_name_plural = "Mediciones Canónicas"

    def __str__(self):
        return (
            f"{self.estacion.nombre} | {self.timestamp} | "
            f"{self.variable} ({self.frecuencia}): {self.valor}"
        )
