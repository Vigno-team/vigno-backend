"""Admin de cuentas: un solo rol por cuenta y cada alta, edición o baja en la bitácora.

Mientras no exista el CRUD de usuarios por API, aquí un administrador crea cuentas y
les asigna el rol.
"""

from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.contrib.auth.models import User
from django.db import transaction

from apps.auditoria.registro import Accion, instantanea_usuario, registrar
from apps.cuentas.models import debe_cambiar_clave
from apps.cuentas.roles import ROLES


class FormularioUsuario(UserChangeForm):
    def clean_groups(self):
        grupos = self.cleaned_data["groups"]
        roles = sorted(grupo.name for grupo in grupos if grupo.name in ROLES)
        if len(roles) > 1:
            raise forms.ValidationError(
                f"Una cuenta tiene un solo rol y elegiste {len(roles)}: {', '.join(roles)}."
            )
        return grupos


admin.site.unregister(User)

# E1C-138: el admin tiene su propio login (sesión, sin token), así que la regla del cambio de
# clave obligatorio se aplica también aquí. Sin esto, admin@sistema.local / admin entraría al
# admin sin cambiar la clave pública.
_permiso_del_admin = admin.site.has_permission


def _permiso_con_clave_al_dia(request):
    return _permiso_del_admin(request) and not debe_cambiar_clave(request.user)


admin.site.has_permission = _permiso_con_clave_al_dia


@admin.register(User)
class UsuarioAdmin(UserAdmin):
    form = FormularioUsuario

    def save_model(self, request, obj, form, change):
        # Cómo estaba antes: se lee de la base porque obj ya trae los cambios del formulario.
        request.auditoria_anterior = (
            instantanea_usuario(User.objects.get(pk=obj.pk)) if change else None
        )
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        # Los grupos (el rol) se guardan aquí, después de save_model: recién ahora se sabe
        # cómo quedó la cuenta. El admin envuelve todo en una transacción.
        super().save_related(request, form, formsets, change)
        registrar(
            Accion.USUARIO_EDICION if change else Accion.USUARIO_ALTA,
            request=request,
            objeto=form.instance,
            anterior=getattr(request, "auditoria_anterior", None),
            nuevo=instantanea_usuario(form.instance),
        )

    def delete_model(self, request, obj):
        anterior, pk = instantanea_usuario(obj), obj.pk
        super().delete_model(request, obj)
        registrar(
            Accion.USUARIO_BAJA,
            request=request,
            tipo_objeto="auth.User",
            id_objeto=pk,
            anterior=anterior,
        )

    def delete_queryset(self, request, queryset):
        # "Eliminar seleccionados": uno por uno, para que cada baja quede registrada.
        with transaction.atomic():
            for usuario in queryset:
                self.delete_model(request, usuario)
