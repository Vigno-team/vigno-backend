from django.contrib import admin

from apps.configuracion.models import ConfiguracionInstancia


@admin.register(ConfiguracionInstancia)
class ConfiguracionInstanciaAdmin(admin.ModelAdmin):
    """Solo para mirar: los cambios van por la API, que los deja en la bitácora."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
