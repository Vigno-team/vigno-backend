"""E1C-138: administrador por defecto y cambio de clave obligatorio en el primer ingreso."""

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.auditoria.models import RegistroAuditoria
from apps.cuentas.management.commands.crear_admin_inicial import (
    CLAVE_POR_DEFECTO,
    CORREO_POR_DEFECTO,
)
from apps.cuentas.models import Perfil
from apps.cuentas.roles import ADMINISTRADOR, asignar_rol
from apps.cuentas.tests.test_auth import LECTURAS_PUBLICAS, rutas_api
from conftest import CLAVE_PRUEBA

pytestmark = pytest.mark.django_db

LOGIN = "/api/v1/auth/token"
YO = "/api/v1/auth/yo"
CAMBIAR = "/api/v1/auth/cambiar-clave"
NUEVA_CLAVE = "Primera-clave-propia-2026"


@pytest.fixture(autouse=True)
def sin_variables(monkeypatch, settings):
    monkeypatch.delenv("DJANGO_SUPERUSER_EMAIL", raising=False)
    monkeypatch.delenv("DJANGO_SUPERUSER_PASSWORD", raising=False)
    settings.ADMIN_POR_DEFECTO = True


def entrar(correo=CORREO_POR_DEFECTO, clave=CLAVE_POR_DEFECTO):
    return APIClient().post(LOGIN, {"email": correo, "password": clave}, format="json")


def con_bearer(token):
    return APIClient(HTTP_AUTHORIZATION=f"Bearer {token}")


@pytest.fixture
def sesion_pendiente():
    """Login del administrador por defecto recién creado."""
    call_command("crear_admin_inicial")
    return entrar().json()


# --- crear_admin_inicial ---------------------------------------------------------------------


def test_en_una_base_vacia_se_crea_el_administrador_por_defecto():
    call_command("crear_admin_inicial")

    admin = User.objects.get(email=CORREO_POR_DEFECTO)
    assert admin.is_superuser and admin.is_staff and admin.is_active
    assert admin.check_password(CLAVE_POR_DEFECTO)
    assert admin.perfil.debe_cambiar_clave is True
    respuesta = entrar()
    assert respuesta.status_code == 200
    assert respuesta.json()["usuario"]["rol"] == "administrador"
    assert respuesta.json()["usuario"]["debe_cambiar_clave"] is True


def test_la_creacion_queda_en_la_bitacora_sin_la_clave():
    call_command("crear_admin_inicial")

    registro = RegistroAuditoria.objects.get(accion=RegistroAuditoria.Accion.USUARIO_ALTA)
    assert registro.usuario is None  # lo hizo el sistema al arrancar
    assert registro.valor_nuevo["email"] == CORREO_POR_DEFECTO
    assert registro.valor_nuevo["debe_cambiar_clave"] is True
    assert CLAVE_POR_DEFECTO not in str(registro.valor_nuevo.get("password", ""))
    assert "password" not in registro.valor_nuevo


def test_con_un_superusuario_existente_no_se_toca_nada(django_user_model):
    existente = django_user_model.objects.create_superuser(
        username="jefa@vigno.cl", email="jefa@vigno.cl", password=CLAVE_PRUEBA
    )
    antes = list(User.objects.values())

    call_command("crear_admin_inicial")

    assert list(User.objects.values()) == antes
    assert not Perfil.objects.exists()
    existente.refresh_from_db()
    assert existente.check_password(CLAVE_PRUEBA)
    assert not RegistroAuditoria.objects.exists()


def test_un_administrador_por_grupo_tambien_cuenta(django_user_model):
    cuenta = django_user_model.objects.create_user(
        username="jefa@vigno.cl", email="jefa@vigno.cl", password=CLAVE_PRUEBA
    )
    asignar_rol(cuenta, ADMINISTRADOR)

    call_command("crear_admin_inicial")

    assert not User.objects.filter(email=CORREO_POR_DEFECTO).exists()


def test_con_administrador_existente_tampoco_se_usan_las_variables(django_user_model, monkeypatch):
    django_user_model.objects.create_superuser(
        username="jefa@vigno.cl", email="jefa@vigno.cl", password=CLAVE_PRUEBA
    )
    monkeypatch.setenv("DJANGO_SUPERUSER_EMAIL", "otra@vigno.cl")
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "Admin-inicial-2026")

    call_command("crear_admin_inicial")

    assert not User.objects.filter(email="otra@vigno.cl").exists()


def test_un_administrador_desactivado_no_cuenta(django_user_model):
    django_user_model.objects.create_superuser(
        username="vieja@vigno.cl", email="vieja@vigno.cl", password=CLAVE_PRUEBA, is_active=False
    )

    call_command("crear_admin_inicial")

    assert User.objects.get(email=CORREO_POR_DEFECTO).perfil.debe_cambiar_clave


def test_con_variables_de_entorno_se_usan_ellas_y_no_la_cuenta_por_defecto(monkeypatch):
    monkeypatch.setenv("DJANGO_SUPERUSER_EMAIL", "Jefa@Vigno.cl")
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "Admin-inicial-2026")

    call_command("crear_admin_inicial")

    assert not User.objects.filter(email=CORREO_POR_DEFECTO).exists()
    admin = User.objects.get(email="jefa@vigno.cl")
    assert admin.is_superuser
    assert admin.perfil.debe_cambiar_clave is False  # eligió su propia clave
    assert (
        entrar("jefa@vigno.cl", "Admin-inicial-2026").json()["usuario"]["debe_cambiar_clave"]
        is False
    )


def test_no_convierte_en_administrador_una_cuenta_existente(django_user_model):
    comun = django_user_model.objects.create_user(
        username=CORREO_POR_DEFECTO, email=CORREO_POR_DEFECTO, password=CLAVE_PRUEBA
    )

    call_command("crear_admin_inicial")

    comun.refresh_from_db()
    assert not comun.is_superuser
    assert comun.check_password(CLAVE_PRUEBA)


# --- cambio de clave obligatorio ---------------------------------------------------------------


def casos_con_cambio_pendiente():
    for ruta in sorted(r for r in rutas_api() if not r.startswith("/api/v1/auth/")):
        for metodo in ("get", "post"):
            # Las lecturas públicas no miran el token (E1C-96): con o sin él responden igual.
            if not (metodo == "get" and ruta in LECTURAS_PUBLICAS):
                yield metodo, ruta


@pytest.mark.parametrize("metodo,ruta", list(casos_con_cambio_pendiente()))
def test_con_cambio_pendiente_todo_responde_403_salvo_auth(
    sesion_pendiente, settings, metodo, ruta
):
    settings.API_LECTURA_PUBLICA = True  # tampoco las lecturas públicas, si manda su token
    respuesta = getattr(con_bearer(sesion_pendiente["access"]), metodo)(ruta, {}, format="json")

    assert respuesta.status_code == 403, (metodo, ruta, respuesta.status_code)
    assert respuesta.json() == {
        "detail": "Tienes que cambiar tu clave antes de seguir.",
        "code": "cambio_de_clave_requerido",
    }


def test_con_cambio_pendiente_igual_ve_la_marca(sesion_pendiente):
    # La pantalla de cambio de clave también muestra el logo y los colores (E1C-96).
    respuesta = con_bearer(sesion_pendiente["access"]).get("/api/v1/configuracion")

    assert respuesta.status_code == 200


def test_con_cambio_pendiente_funcionan_yo_refresh_y_logout(sesion_pendiente):
    cliente = con_bearer(sesion_pendiente["access"])

    yo = cliente.get(YO)
    assert yo.status_code == 200 and yo.json()["debe_cambiar_clave"] is True
    nuevos = APIClient().post(
        "/api/v1/auth/refresh", {"refresh": sesion_pendiente["refresh"]}, format="json"
    )
    assert nuevos.status_code == 200
    respuesta = con_bearer(nuevos.json()["access"]).post(
        "/api/v1/auth/logout", {"refresh": nuevos.json()["refresh"]}, format="json"
    )
    assert respuesta.status_code == 204


def test_despues_de_cambiar_la_clave_todo_funciona(sesion_pendiente):
    respuesta = con_bearer(sesion_pendiente["access"]).post(
        CAMBIAR, {"clave_actual": CLAVE_POR_DEFECTO, "clave_nueva": NUEVA_CLAVE}, format="json"
    )

    assert respuesta.status_code == 200
    cliente = con_bearer(respuesta.json()["access"])
    assert cliente.get(YO).json()["debe_cambiar_clave"] is False
    assert cliente.get("/api/v1/datos").status_code != 403
    assert cliente.get("/api/v1/cargas").status_code == 200
    assert User.objects.get(email=CORREO_POR_DEFECTO).perfil.debe_cambiar_clave is False
    # la clave pública ya no sirve
    assert entrar().status_code == 401
    assert entrar(clave=NUEVA_CLAVE).json()["usuario"]["debe_cambiar_clave"] is False


def test_el_cambio_queda_en_la_bitacora(sesion_pendiente):
    con_bearer(sesion_pendiente["access"]).post(
        CAMBIAR, {"clave_actual": CLAVE_POR_DEFECTO, "clave_nueva": NUEVA_CLAVE}, format="json"
    )

    registro = RegistroAuditoria.objects.get(accion=RegistroAuditoria.Accion.CLAVE_CAMBIADA)
    assert registro.usuario.email == CORREO_POR_DEFECTO
    assert registro.valor_nuevo == {"cambio_obligatorio": True}


def test_la_clave_nueva_tiene_que_cumplir_las_reglas(sesion_pendiente):
    respuesta = con_bearer(sesion_pendiente["access"]).post(
        CAMBIAR, {"clave_actual": CLAVE_POR_DEFECTO, "clave_nueva": "admin123"}, format="json"
    )

    assert respuesta.status_code == 400
    assert User.objects.get(email=CORREO_POR_DEFECTO).perfil.debe_cambiar_clave is True


def test_las_cuentas_sin_perfil_no_quedan_bloqueadas(cliente_con_token):
    # Las cuentas creadas antes de E1C-138 no tienen perfil: siguen funcionando.
    assert not Perfil.objects.exists()
    assert cliente_con_token.get("/api/v1/cargas").status_code == 200


def test_el_admin_de_django_tambien_pide_cambiar_la_clave(client):
    call_command("crear_admin_inicial")
    admin = User.objects.get(email=CORREO_POR_DEFECTO)
    client.force_login(admin)

    assert client.get("/admin/").status_code == 302  # vuelve al login del admin

    Perfil.objects.filter(usuario=admin).update(debe_cambiar_clave=False)
    assert client.get("/admin/").status_code == 200
