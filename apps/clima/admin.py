"""Registro en el admin de Django para la app `clima`."""

from django.contrib import admin

from .models import ConfiguracionCalidad, Estacion, IndiceClimatico, MedicionHoraria, ResumenDiario


# Visualizar tablas tablas estandarizadas en Admin
@admin.register(Estacion)
class EstacionAdmin(admin.ModelAdmin):
    list_display = ("nombre", "codigo", "subzona", "propietario")
    search_fields = ("nombre", "codigo")


@admin.register(MedicionHoraria)
class MedicionHorariaAdmin(admin.ModelAdmin):
    list_display = ("estacion", "timestamp", "variable", "valor", "motivo_nulo")
    list_filter = ("estacion", "variable")
    search_fields = ("variable",)


@admin.register(ConfiguracionCalidad)
class ConfiguracionCalidadAdmin(admin.ModelAdmin):
    list_display = ("clave", "umbral_pct", "horas_minimas_dia", "actualizado_en")





@admin.register(ResumenDiario)
class ResumenDiarioAdmin(admin.ModelAdmin):
    list_display = ("estacion", "fecha", "temporada", "tmedia", "tmax", "tmin", "confiable")
    list_filter = ("estacion", "temporada", "confiable")


@admin.register(IndiceClimatico)
class IndiceClimaticoAdmin(admin.ModelAdmin):
    list_display = ("estacion", "temporada", "indice", "valor", "clasificacion", "confiable")
    list_filter = ("indice", "estacion", "temporada", "confiable")
