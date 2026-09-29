from django.db import models

class RegistroCarga(models.Model):
    fecha_carga = models.DateTimeField(auto_now_add=True, help_text="Fecha y hora en que se corrio el script")
    archivo = models.CharField(max_length=255, help_text="Ruta o nombre del Excel origen")
    estacion = models.CharField(max_length=100)
    formato_detectado = models.CharField(max_length=50, null=True, blank=True)
    
    filas_leidas = models.IntegerField(default=0)
    filas_aceptadas = models.IntegerField(default=0)
    filas_rechazadas = models.IntegerField(default=0)
    
    detalle_rechazos = models.JSONField(null=True, blank=True, help_text="Motivos de rechazo de filas")
    columnas_descartadas = models.CharField(max_length=255, null=True, blank=True, help_text="Constancia del descarte de Abejas")
    
    registros_insertados = models.IntegerField(default=0)
    registros_actualizados = models.IntegerField(default=0)
    
    usuario = models.CharField(max_length=100, default="Sistema (Terminal)")

    class Meta:
        verbose_name_plural = "Registros de Carga"

    def __str__(self):
        return f"{self.fecha_carga.strftime('%Y-%m-%d %H:%M')} | {self.estacion} ({self.registros_insertados} nuevos)"