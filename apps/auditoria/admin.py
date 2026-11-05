from django.contrib import admin

from apps.auditoria.models import RegistroAuditoria


@admin.register(RegistroAuditoria)
class RegistroAuditoriaAdmin(admin.ModelAdmin):
    """Solo lectura: la bitácora no se agrega, edita ni borra desde el admin."""

    list_display = ("fecha", "usuario", "accion", "tipo_objeto", "id_objeto", "ip")
    list_filter = ("accion", "fecha")
    search_fields = ("usuario__email", "id_objeto")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
