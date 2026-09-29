from django.db import models

class Estacion(models.Model):
    nombre = models.CharField(max_length=100)
    # Por el momento solo tiene el campo nombre para conectar las mediciones
    
    class Meta:
        verbose_name_plural = "Estaciones"

    def __str__(self):
        return self.nombre


class MedicionCanonica(models.Model):
    estacion = models.ForeignKey(Estacion, on_delete=models.CASCADE, related_name='mediciones')
    timestamp = models.DateTimeField(
        help_text="Fecha de la medicion"
    )
    variable = models.CharField(
        max_length=50, 
        help_text="Nombre estandarizado de la variable"
    )
    valor = models.FloatField(
        null=True, 
        blank=True,
        help_text="Valor numerico de la medicion ('Nulo' si no hay dato valido)"
    )
    motivo_nulo = models.CharField(
        max_length=255, 
        null=True, 
        blank=True,
        help_text="Razon por la cual el valor es nulo"
    )

    class Meta:
        # Evitamos duplicados: misma estación, misma fecha, misma variable
        unique_together = ('estacion', 'timestamp', 'variable')
        indexes = [
            models.Index(fields=['estacion', 'timestamp']),
            models.Index(fields=['variable']),
        ]
        verbose_name_plural = "Mediciones Canónicas"

    def __str__(self):
        return f"{self.estacion.nombre} | {self.timestamp} | {self.variable}: {self.valor}"