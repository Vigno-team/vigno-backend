"""cada acción deja su registro y la bitácora solo crece."""

from datetime import timedelta

import pytest
from django.contrib import admin
from django.db.models import ProtectedError
from django.test import RequestFactory
from django.utils import timezone
from rest_framework.test import APIClient

from apps.auditoria.models import RegistroAuditoria, SoloAgregar
from apps.auditoria.registro import Accion, registrar
from apps.clima import views as vistas_clima
from apps.clima.models import Estacion
from apps.cuentas.roles import LECTOR, asignar_rol
from conftest import CLAVE_PRUEBA, CORREO_PRUEBA

pytestmark = pytest.mark.django_db

URL = "/api/v1/auditoria"


def entrar(correo, clave):
    return APIClient().post(
        "/api/v1/auth/token", {"email": correo, "password": clave}, format="json"
    )


class FormularioFalso:
    """Lo mínimo que save_related necesita del formulario del admin."""

    def __init__(self, instancia):
        self.instance = instancia

    def save_m2m(self):
        pass


def peticion_admin(cuenta):
    request = RequestFactory().post("/admin/")
    request.user = cuenta
    return request


@pytest.fixture
def superusuario(django_user_model):
    return django_user_model.objects.create_superuser(
        "root@vigno.cl", "root@vigno.cl", CLAVE_PRUEBA
    )


# --- qué acciones se registran ---------------------------------------------------------------


def test_login_correcto_y_fallidos_quedan_registrados(usuario):
    assert entrar(CORREO_PRUEBA, CLAVE_PRUEBA).status_code == 200
    assert entrar(CORREO_PRUEBA, "clave-equivocada").status_code == 401
    assert entrar("nadie@vigno.cl", "clave-equivocada").status_code == 401

    correcto = RegistroAuditoria.objects.get(accion=Accion.LOGIN_CORRECTO)
    assert correcto.usuario == usuario and correcto.ip == "127.0.0.1"
    fallidos = RegistroAuditoria.objects.filter(accion=Accion.LOGIN_FALLIDO).order_by("pk")
    assert [f.usuario for f in fallidos] == [None, None]
    assert [f.valor_nuevo["email"] for f in fallidos] == [CORREO_PRUEBA, "nadie@vigno.cl"]


def test_alta_edicion_y_baja_de_usuario_desde_el_admin(superusuario, django_user_model):
    modelo = admin.site._registry[django_user_model]
    request = peticion_admin(superusuario)
    nueva = django_user_model(username="nueva@vigno.cl", email="nueva@vigno.cl")

    modelo.save_model(request, nueva, FormularioFalso(nueva), change=False)
    modelo.save_related(request, FormularioFalso(nueva), [], change=False)
    nueva.first_name = "Nueva"
    modelo.save_model(request, nueva, FormularioFalso(nueva), change=True)
    asignar_rol(nueva, LECTOR)  # el admin guarda los grupos justo antes del registro
    modelo.save_related(request, FormularioFalso(nueva), [], change=True)
    pk = nueva.pk
    modelo.delete_model(request, nueva)

    alta, edicion, baja = RegistroAuditoria.objects.filter(accion__startswith="usuario_").order_by(
        "pk"
    )
    assert [alta.accion, edicion.accion, baja.accion] == [
        Accion.USUARIO_ALTA,
        Accion.USUARIO_EDICION,
        Accion.USUARIO_BAJA,
    ]
    assert {alta.usuario, edicion.usuario, baja.usuario} == {superusuario}
    assert "password" not in alta.valor_nuevo
    assert (edicion.valor_anterior["first_name"], edicion.valor_nuevo["first_name"]) == (
        "",
        "Nueva",
    )
    assert (edicion.valor_anterior["rol"], edicion.valor_nuevo["rol"]) == (None, LECTOR)
    assert baja.id_objeto == str(pk) and baja.valor_anterior["email"] == "nueva@vigno.cl"


def test_edicion_y_baja_de_estacion_desde_el_admin(superusuario):
    modelo = admin.site._registry[Estacion]
    request = peticion_admin(superusuario)
    estacion = Estacion.objects.create(
        nombre="Villa Nueva", codigo="villa-nueva", latitud=-35.9, longitud=-72.3
    )

    estacion.propietario = "Casas Patronales"
    modelo.save_model(request, estacion, None, change=True)
    pk = estacion.pk
    modelo.delete_model(request, estacion)

    edicion = RegistroAuditoria.objects.get(accion=Accion.ESTACION_EDICION)
    assert edicion.valor_anterior["propietario"] is None
    assert edicion.valor_nuevo["propietario"] == "Casas Patronales"
    baja = RegistroAuditoria.objects.get(accion=Accion.ESTACION_BAJA)
    assert baja.id_objeto == str(pk) and baja.valor_anterior["codigo"] == "villa-nueva"


def test_si_falla_la_bitacora_no_se_crea_la_estacion(cliente_con_token, monkeypatch):
    def fallar(*args, **kwargs):
        raise RuntimeError("bitácora caída")

    monkeypatch.setattr(vistas_clima, "registrar", fallar)
    nueva = {"nombre": "Villa Nueva", "latitud": -35.9, "longitud": -72.3}

    with pytest.raises(RuntimeError):
        cliente_con_token.post("/api/v1/estaciones", nueva, format="json")
    assert not Estacion.objects.filter(nombre="Villa Nueva").exists()


# --- solo se agregan registros -------------------------------------------------------------


def test_la_bitacora_no_se_edita_ni_se_borra(usuario):
    registro = registrar(Accion.LOGIN_CORRECTO, usuario=usuario)

    registro.accion = Accion.LOGIN_FALLIDO
    with pytest.raises(SoloAgregar):
        registro.save()
    with pytest.raises(SoloAgregar):
        registro.delete()
    with pytest.raises(SoloAgregar):
        RegistroAuditoria.objects.filter(pk=registro.pk).update(ip="10.0.0.1")
    with pytest.raises(SoloAgregar):
        RegistroAuditoria.objects.all().delete()
    assert RegistroAuditoria.objects.get(pk=registro.pk).accion == Accion.LOGIN_CORRECTO


def test_el_admin_de_la_bitacora_es_solo_lectura(superusuario):
    modelo = admin.site._registry[RegistroAuditoria]
    request = peticion_admin(superusuario)

    assert modelo.has_view_permission(request)
    assert not modelo.has_add_permission(request)
    assert not modelo.has_change_permission(request)
    assert not modelo.has_delete_permission(request)


def test_una_cuenta_con_historial_no_se_borra(usuario):
    entrar(CORREO_PRUEBA, CLAVE_PRUEBA)

    with pytest.raises(ProtectedError):
        usuario.delete()


# --- GET /api/v1/auditoria -----------------------------------------------------------------


def test_solo_el_administrador_ve_la_bitacora(cliente_admin, cliente_con_token, cliente_lector):
    assert cliente_admin.get(URL).status_code == 200
    assert cliente_con_token.get(URL).status_code == 403  # editor
    assert cliente_lector.get(URL).status_code == 403
    assert APIClient().get(URL).status_code == 401


def test_el_editor_no_administra_usuarios(client, usuario):
    # El CRUD de usuarios por API llega en E1C-133; hoy se administran en el admin.
    client.force_login(usuario)
    assert client.get("/admin/auth/user/").status_code == 302  # lo manda al login del admin


def test_la_bitacora_filtra_y_pagina(cliente_admin, usuario):
    propio = registrar(Accion.LOGIN_CORRECTO, usuario=usuario)
    registrar(Accion.LOGIN_FALLIDO, nuevo={"email": "nadie@vigno.cl"})
    hoy = timezone.localdate()

    datos = cliente_admin.get(URL, {"usuario": CORREO_PRUEBA}).json()
    assert set(datos) == {"count", "next", "previous", "results"}
    assert datos["count"] == 1 and datos["results"][0]["id"] == propio.pk
    assert datos["results"][0]["usuario"] == CORREO_PRUEBA
    assert cliente_admin.get(URL, {"usuario": usuario.pk}).json()["count"] == 1
    fallido = cliente_admin.get(URL, {"accion": "login_fallido"}).json()["results"][0]
    assert fallido["usuario"] is None and fallido["valor_nuevo"] == {"email": "nadie@vigno.cl"}
    assert cliente_admin.get(URL, {"desde": hoy, "hasta": hoy}).json()["count"] == 2
    assert cliente_admin.get(URL, {"desde": hoy + timedelta(days=1)}).json()["count"] == 0


@pytest.mark.parametrize(
    "filtros",
    [{"accion": "inventada"}, {"desde": "ayer"}, {"desde": "2026-11-05", "hasta": "2026-11-04"}],
)
def test_filtros_invalidos_dan_400(cliente_admin, filtros):
    assert cliente_admin.get(URL, filtros).status_code == 400
