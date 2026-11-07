"""Registro en el admin de Django para la app `clima`."""

from django.contrib import admin
from django.db import transaction

from apps.auditoria.registro import Accion, instantanea_estacion, registrar

from .models import ConfiguracionCalidad, Estacion, IndiceClimatico, MedicionHoraria, ResumenDiario


# Visualizar tablas tablas estandarizadas en Admin
@admin.register(Estacion)
class EstacionAdmin(admin.ModelAdmin):
    list_display = ("nombre", "codigo", "subzona", "propietario", "latitud", "longitud")
    search_fields = ("nombre", "codigo")

    # cada alta, edición o baja desde el admin queda en la bitácora. El admin ya
    # envuelve cada guardado y cada borrado en una transacción.
    def save_model(self, request, obj, form, change):
        anterior = instantanea_estacion(Estacion.objects.get(pk=obj.pk)) if change else None
        super().save_model(request, obj, form, change)
        registrar(
            Accion.ESTACION_EDICION if change else Accion.ESTACION_ALTA,
            request=request,
            objeto=obj,
            anterior=anterior,
            nuevo=instantanea_estacion(obj),
        )

    def delete_model(self, request, obj):
        anterior, pk = instantanea_estacion(obj), obj.pk
        super().delete_model(request, obj)
        registrar(
            Accion.ESTACION_BAJA,
            request=request,
            tipo_objeto="clima.Estacion",
            id_objeto=pk,
            anterior=anterior,
        )

    def delete_queryset(self, request, queryset):
        # "Eliminar seleccionados": una por una, para que cada baja quede registrada.
        with transaction.atomic():
            for estacion in queryset:
                self.delete_model(request, estacion)


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
