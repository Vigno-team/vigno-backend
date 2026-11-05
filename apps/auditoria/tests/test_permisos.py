"""cada rol ve y hace solo lo que le corresponde."""

import pytest
from django.contrib.auth.models import AnonymousUser, Group
from django.core.exceptions import ValidationError
from rest_framework.test import APIRequestFactory

from apps.cuentas.admin import FormularioUsuario
from apps.cuentas.permisos import EsAdministrador, PuedeEditar, PuedeLeer
from apps.cuentas.roles import ADMINISTRADOR, EDITOR, LECTOR, ROLES, asignar_rol, rol_de
from conftest import CLAVE_PRUEBA, cliente_de, crear_cuenta

pytestmark = pytest.mark.django_db


def permite(permiso, usuario, metodo="get", vista=None):
    request = getattr(APIRequestFactory(), metodo)("/")
    request.user = usuario
    return permiso().has_permission(request, vista)


@pytest.mark.parametrize(
    "rol,administra,edita,lee",
    [
        (ADMINISTRADOR, True, True, True),
        (EDITOR, False, True, True),
        (LECTOR, False, False, True),
        (None, False, False, False),
    ],
)
def test_cada_rol_tiene_sus_permisos(django_user_model, rol, administra, edita, lee):
    cuenta = crear_cuenta(django_user_model, "cuenta@vigno.cl", rol)

    assert permite(EsAdministrador, cuenta) is administra
    assert permite(PuedeEditar, cuenta) is edita
    assert permite(PuedeLeer, cuenta) is lee


def test_el_superusuario_es_administrador_sin_grupo(django_user_model):
    cuenta = django_user_model.objects.create_superuser(
        "root@vigno.cl", "root@vigno.cl", CLAVE_PRUEBA
    )
    assert not cuenta.groups.exists()
    assert permite(EsAdministrador, cuenta)


def test_un_anonimo_no_pasa_ningun_permiso():
    for permiso in (EsAdministrador, PuedeEditar, PuedeLeer):
        assert not permite(permiso, AnonymousUser())


def test_la_lectura_publica_solo_abre_lecturas_del_dashboard(settings):
    settings.API_LECTURA_PUBLICA = True

    class Dashboard:
        lectura_publica = True

    assert permite(PuedeLeer, AnonymousUser(), vista=Dashboard())
    assert not permite(PuedeLeer, AnonymousUser(), metodo="post", vista=Dashboard())
    assert not permite(PuedeLeer, AnonymousUser())  # cargas, correcciones, auditoría


def test_una_cuenta_sin_rol_recibe_403_pero_ve_su_cuenta(django_user_model):
    cliente = cliente_de(crear_cuenta(django_user_model, "sinrol@vigno.cl"))

    assert cliente.get("/api/v1/cargas").status_code == 403
    assert cliente.get("/api/v1/auth/yo").json()["rol"] is None


def test_la_migracion_crea_los_tres_grupos():
    assert set(Group.objects.filter(name__in=ROLES).values_list("name", flat=True)) == set(ROLES)


def test_asignar_rol_deja_un_solo_rol(usuario):
    asignar_rol(usuario, LECTOR)

    assert list(usuario.groups.values_list("name", flat=True)) == [LECTOR]
    assert rol_de(usuario) == LECTOR
    with pytest.raises(ValueError):
        asignar_rol(usuario, "jefe")


def test_el_admin_no_deja_guardar_dos_roles(usuario):
    formulario = FormularioUsuario(instance=usuario)
    formulario.cleaned_data = {"groups": Group.objects.filter(name__in=[EDITOR, LECTOR])}

    with pytest.raises(ValidationError):
        formulario.clean_groups()
