"""recuperar la clave por correo."""

import json
import os
import re
import secrets
import smtplib
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from django.contrib.auth.tokens import default_token_generator
from rest_framework.test import APIClient

from apps.auditoria.models import RegistroAuditoria
from apps.auditoria.registro import Accion
from apps.configuracion.models import ConfiguracionInstancia
from apps.cuentas.models import Perfil
from apps.cuentas.serializers import ENLACE_INVALIDO
from conftest import CLAVE_PRUEBA, CORREO_PRUEBA

pytestmark = pytest.mark.django_db

DISPONIBLE = "/api/v1/auth/recuperacion"
RECUPERAR = "/api/v1/auth/recuperar-clave"
RESTABLECER = "/api/v1/auth/restablecer-clave"
LOGIN = "/api/v1/auth/token"
REFRESH = "/api/v1/auth/refresh"
YO = "/api/v1/auth/yo"
NUEVA_CLAVE = "Cosecha-tardia-2027"
FRONTEND = "https://vigno.ejemplo.cl"
RAIZ = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def correo_en_memoria(settings):
    # locmem: los correos quedan en mailoutbox en vez de salir a un servidor.
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.RECUPERACION_CLAVE_HABILITADA = True
    settings.FRONTEND_URL = FRONTEND


def pedir(correo=CORREO_PRUEBA, **extra):
    return APIClient().post(RECUPERAR, {"email": correo}, format="json", **extra)


def datos_del_enlace(correo):
    """uid y token del enlace que trae el correo, como los leería el frontend."""
    enlace = re.search(rf"{re.escape(FRONTEND)}\S+", correo.body).group()
    parametros = parse_qs(urlparse(enlace).query)
    return {"uid": parametros["uid"][0], "token": parametros["token"][0]}


def restablecer(datos, clave=NUEVA_CLAVE):
    return APIClient().post(RESTABLECER, {**datos, "clave_nueva": clave}, format="json")


def entrar(clave):
    return APIClient().post(LOGIN, {"email": CORREO_PRUEBA, "password": clave}, format="json")


# --- disponible ----------------------------------------------------------------------------------


def test_disponible_es_publica_y_no_mira_el_token(settings):
    vencido = APIClient(HTTP_AUTHORIZATION="Bearer token-vencido")

    assert APIClient().get(DISPONIBLE).json() == {"disponible": True}
    assert vencido.get(DISPONIBLE).status_code == 200
    settings.RECUPERACION_CLAVE_HABILITADA = False
    assert APIClient().get(DISPONIBLE).json() == {"disponible": False}


# --- pedir el enlace -----------------------------------------------------------------------------


def test_se_envia_el_correo_con_un_enlace_valido(usuario, mailoutbox):
    respuesta = pedir()

    assert respuesta.status_code == 202
    assert len(mailoutbox) == 1
    correo = mailoutbox[0]
    organizacion = ConfiguracionInstancia.actual().nombre_organizacion
    assert correo.to == [CORREO_PRUEBA]
    assert organizacion in correo.subject and organizacion in correo.body
    assert f"{FRONTEND}/restablecer-clave?uid=" in correo.body
    assert "1 hora" in correo.body
    assert CORREO_PRUEBA not in correo.body  # solo el enlace y cuánto dura
    assert default_token_generator.check_token(usuario, datos_del_enlace(correo)["token"])


def test_el_correo_no_distingue_mayusculas_ni_espacios(usuario, mailoutbox):
    assert pedir("  Analista@VIGNO.cl ").status_code == 202
    assert len(mailoutbox) == 1


def test_un_correo_sin_cuenta_da_la_misma_respuesta_y_no_envia_nada(usuario, mailoutbox):
    sin_cuenta = pedir("nadie@vigno.cl")

    assert mailoutbox == []
    assert not RegistroAuditoria.objects.filter(accion=Accion.RECUPERACION_SOLICITADA).exists()
    con_cuenta = pedir()
    assert sin_cuenta.status_code == con_cuenta.status_code == 202
    assert sin_cuenta.json() == con_cuenta.json()
    assert len(mailoutbox) == 1


def test_una_cuenta_desactivada_no_recibe_correo(usuario, mailoutbox):
    usuario.is_active = False
    usuario.save()

    respuesta = pedir()

    assert respuesta.status_code == 202
    assert mailoutbox == []
    registro = RegistroAuditoria.objects.get(accion=Accion.RECUPERACION_SOLICITADA)
    assert registro.valor_nuevo == {"correo_enviado": False}


def test_si_el_servidor_de_correo_falla_la_respuesta_no_cambia(usuario, monkeypatch):
    def falla(*args, **kwargs):
        raise smtplib.SMTPServerDisconnected("sin conexión")

    monkeypatch.setattr("apps.cuentas.recuperacion.send_mail", falla)

    respuesta = pedir()

    assert respuesta.status_code == 202
    registro = RegistroAuditoria.objects.get(accion=Accion.RECUPERACION_SOLICITADA)
    assert registro.valor_nuevo == {"correo_enviado": False}


# --- elegir la clave nueva -----------------------------------------------------------------------


def test_con_el_enlace_se_elige_una_clave_nueva_y_se_entra_con_ella(usuario, mailoutbox):
    pedir()

    respuesta = restablecer(datos_del_enlace(mailoutbox[0]))

    assert respuesta.status_code == 204
    assert entrar(NUEVA_CLAVE).status_code == 200
    assert entrar(CLAVE_PRUEBA).status_code == 401


def test_restablecer_quita_el_cambio_de_clave_obligatorio(usuario, mailoutbox):
    Perfil.objects.update_or_create(usuario=usuario, defaults={"debe_cambiar_clave": True})
    pedir()

    assert restablecer(datos_del_enlace(mailoutbox[0])).status_code == 204
    assert Perfil.objects.get(usuario=usuario).debe_cambiar_clave is False


def test_despues_de_restablecer_las_sesiones_anteriores_ya_no_sirven(usuario, mailoutbox):
    # Primero se entra: el enlace se emite después, con ese último ingreso.
    sesion = entrar(CLAVE_PRUEBA).json()
    pedir()

    assert restablecer(datos_del_enlace(mailoutbox[0])).status_code == 204
    refresco = APIClient().post(REFRESH, {"refresh": sesion["refresh"]}, format="json")
    assert refresco.status_code == 401
    acceso = APIClient(HTTP_AUTHORIZATION=f"Bearer {sesion['access']}")
    assert acceso.get(YO).status_code == 401


def test_un_enlace_vencido_da_400(usuario, mailoutbox, monkeypatch, settings):
    assert settings.PASSWORD_RESET_TIMEOUT == 60 * 60
    pedir()
    datos = datos_del_enlace(mailoutbox[0])
    # Una hora y un segundo después de pedirlo.
    despues = datetime.now() + timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT + 1)
    monkeypatch.setattr(default_token_generator, "_now", lambda: despues)

    respuesta = restablecer(datos)

    assert respuesta.status_code == 400
    assert respuesta.json() == {"token": [ENLACE_INVALIDO]}
    usuario.refresh_from_db()
    assert usuario.check_password(CLAVE_PRUEBA)


@pytest.mark.parametrize("campo", ["token", "uid"])
def test_un_enlace_alterado_da_400(usuario, mailoutbox, campo):
    pedir()
    datos = datos_del_enlace(mailoutbox[0])
    original = datos[campo]
    datos[campo] = original[:-1] + ("A" if original[-1] != "A" else "B")

    respuesta = restablecer(datos)

    assert respuesta.status_code == 400
    assert respuesta.json() == {"token": [ENLACE_INVALIDO]}


def test_un_enlace_ya_usado_da_400(usuario, mailoutbox):
    pedir()
    datos = datos_del_enlace(mailoutbox[0])
    assert restablecer(datos).status_code == 204

    respuesta = restablecer(datos, clave="Otra-clave-de-vendimia-2028")

    assert respuesta.status_code == 400
    assert respuesta.json() == {"token": [ENLACE_INVALIDO]}
    assert entrar(NUEVA_CLAVE).status_code == 200


@pytest.mark.parametrize("clave", ["corta", "12345678901", "password123"])
def test_una_clave_debil_da_400_y_no_cambia_nada(usuario, mailoutbox, clave):
    pedir()

    respuesta = restablecer(datos_del_enlace(mailoutbox[0]), clave=clave)

    assert respuesta.status_code == 400
    assert "clave_nueva" in respuesta.json()
    usuario.refresh_from_db()
    assert usuario.check_password(CLAVE_PRUEBA)


# --- bitácora ------------------------------------------------------------------------------------


def test_la_bitacora_guarda_pedido_y_restablecimiento_sin_token_ni_clave(usuario, mailoutbox):
    pedir()
    datos = datos_del_enlace(mailoutbox[0])
    restablecer(datos)

    pedido = RegistroAuditoria.objects.get(accion=Accion.RECUPERACION_SOLICITADA)
    assert pedido.usuario is None  # quien lo pidió no había entrado
    assert pedido.id_objeto == str(usuario.pk)
    assert pedido.valor_nuevo == {"correo_enviado": True}
    restablecida = RegistroAuditoria.objects.get(accion=Accion.CLAVE_RESTABLECIDA)
    assert restablecida.usuario == usuario
    for registro in RegistroAuditoria.objects.all():
        guardado = json.dumps([registro.valor_anterior, registro.valor_nuevo])
        assert datos["token"] not in guardado
        assert NUEVA_CLAVE not in guardado


# --- límite de pedidos ---------------------------------------------------------------------------


def test_el_cuarto_pedido_en_una_hora_desde_la_misma_ip_da_429(usuario, mailoutbox):
    for i in range(3):
        assert pedir(f"persona{i}@vigno.cl").status_code == 202

    assert pedir().status_code == 429
    assert mailoutbox == []


def test_el_cuarto_pedido_en_una_hora_para_el_mismo_correo_da_429(usuario, mailoutbox):
    for i in range(3):
        assert pedir(REMOTE_ADDR=f"10.0.0.{i}").status_code == 202

    # Desde otra IP y con el correo escrito distinto: cuenta igual.
    assert pedir("ANALISTA@vigno.cl", REMOTE_ADDR="10.0.0.9").status_code == 429
    assert len(mailoutbox) == 3


# --- sin servidor de correo ----------------------------------------------------------------------


def test_apagada_disponible_es_false_y_el_pedido_da_503(settings, usuario, mailoutbox):
    settings.RECUPERACION_CLAVE_HABILITADA = False

    assert APIClient().get(DISPONIBLE).json() == {"disponible": False}
    respuesta = pedir()
    assert respuesta.status_code == 503
    assert "administrador" in respuesta.json()["detail"]
    assert mailoutbox == []


def ajustes_reales(modulo, **variables):
    """Lo que deciden los settings reales de `modulo`, en un proceso nuevo (sin pytest)."""
    codigo = (
        "import json, django; django.setup(); from django.conf import settings as s; "
        "print(json.dumps([s.RECUPERACION_CLAVE_HABILITADA, s.EMAIL_BACKEND]))"
    )
    entorno = {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": modulo,
        "SECRET_KEY": secrets.token_urlsafe(48),
        "POSTGRES_PASSWORD": secrets.token_urlsafe(48),
        **variables,
    }
    resultado = subprocess.run(
        [sys.executable, "-c", codigo], cwd=RAIZ, env=entorno, capture_output=True, text=True
    )
    assert resultado.returncode == 0, resultado.stderr[-500:]
    return json.loads(resultado.stdout.strip().splitlines()[-1])


@pytest.mark.parametrize(
    "modulo,email_host,habilitada,backend",
    [
        ("vigno.settings.production", "", False, "console"),
        ("vigno.settings.production", "smtp.ejemplo.cl", True, "smtp"),
        ("vigno.settings.development", "", True, "console"),
        ("vigno.settings.development", "smtp.ejemplo.cl", True, "smtp"),
    ],
)
def test_la_recuperacion_depende_del_servidor_de_correo(modulo, email_host, habilitada, backend):
    # Sin EMAIL_HOST: en desarrollo, la consola; en producción, apagada.
    assert ajustes_reales(modulo, EMAIL_HOST=email_host) == [
        habilitada,
        f"django.core.mail.backends.{backend}.EmailBackend",
    ]
