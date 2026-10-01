from django.db import models


class Estacion(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    # Campos agregados (Punto 2.2)
    codigo = models.CharField(max_length=50, unique=True, null=True, blank=True)
    subzona = models.CharField(max_length=50, null=True, blank=True)
    propietario = models.CharField(max_length=100, null=True, blank=True)

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

    temporada = models.PositiveSmallIntegerField(
        null=True, blank=True, help_text="Temporada del archivo de origen (ej: 2024)"
    )

    carga = models.ForeignKey(
        "ingesta.RegistroCarga",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="mediciones_generadas",
    )

    class Meta:
        db_table = "medicion_horaria"
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


class ConfiguracionCalidad(models.Model):
    clave = models.CharField(max_length=50, unique=True, default="umbral_completitud_pct")
    umbral_pct = models.FloatField(default=80.0)
    # Campo agregado (Punto 3.2)
    horas_minimas_dia = models.IntegerField(default=20)
    actualizado_en = models.DateTimeField(auto_now=True)

    @classmethod
    def obtener_config(cls):
        obj, _ = cls.objects.get_or_create(
            clave="umbral_completitud_pct", defaults={"umbral_pct": 80.0, "horas_minimas_dia": 20}
        )
        return obj

    @classmethod
    def obtener_umbral(cls) -> float:
        return cls.obtener_config().umbral_pct


class ResumenDiario(models.Model):
    # Cambiado a ForeignKey y nuevos campos (Punto 2.1)
    estacion = models.ForeignKey(Estacion, on_delete=models.CASCADE, db_index=True)
    fecha = models.DateField(db_index=True)
    temporada = models.CharField(max_length=9, db_index=True)

    tmax = models.FloatField(null=True, blank=True)
    tmin = models.FloatField(null=True, blank=True)
    tmedia = models.FloatField(null=True, blank=True)
    amplitud_termica = models.FloatField(null=True, blank=True)
    precipitacion = models.FloatField(null=True, blank=True)

    origen = models.CharField(
        max_length=1, choices=[("D", "Diario"), ("H", "Horario")], default="D"
    )
    horas_validas = models.PositiveSmallIntegerField(null=True, blank=True)
    horas_esperadas = models.PositiveSmallIntegerField(null=True, blank=True)
    confiable = models.BooleanField(default=True)
    motivo_nulo = models.CharField(max_length=255, null=True, blank=True)

    class Meta:
        unique_together = ("estacion", "fecha")
        ordering = ["estacion", "fecha"]
class IndiceClimatico(models.Model):
    estacion = models.ForeignKey(Estacion, on_delete=models.CASCADE)
    temporada = models.CharField(max_length=20)
    indice = models.CharField(max_length=50)
    valor = models.FloatField()
    parametros = models.JSONField(default=dict)
    calculado_en = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('estacion', 'temporada', 'indice')
