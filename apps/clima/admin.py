"""Registro en el admin de Django para la app `clima`."""

from django.contrib import admin

from .models import Estacion, MedicionHoraria


# Visualizar tablas tablas estandarizadas en Admin
@admin.register(Estacion)
class EstacionAdmin(admin.ModelAdmin):
    list_display = ("nombre",)


@admin.register(MedicionHoraria)
class MedicionHorariaAdmin(admin.ModelAdmin):
    list_display = ("estacion", "timestamp", "variable", "valor", "motivo_nulo")
    list_filter = ("estacion", "variable")
    search_fields = ("variable",)
