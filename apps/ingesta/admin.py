from django.contrib import admin
from .models import RegistroCarga

@admin.register(RegistroCarga)
class RegistroCargaAdmin(admin.ModelAdmin):
    list_display = ('fecha_carga', 'estacion', 'archivo', 'filas_leidas', 'filas_aceptadas', 'filas_rechazadas', 'usuario')
    list_filter = ('estacion', 'fecha_carga')