"""E1C-64: login con correo, tokens JWT, cierre de sesión y retiro de X-Api-Key."""

from datetime import timedelta

import pytest
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.urls import URLPattern, URLResolver, get_resolver
from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from conftest import CLAVE_PRUEBA, CORREO_PRUEBA, cliente_de

pytestmark = pytest.mark.django_db

LOGIN = "/api/v1/auth/token"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"
YO = "/api/v1/auth/yo"
CAMBIAR = "/api/v1/auth/cambiar-clave"
NUEVA_CLAVE = "Cosecha-tardia-2027"


@pytest.fixture(autouse=True)
def todo_pide_token(settings):
    # El valor por defecto de API_LECTURA_PUBLICA (conftest.py la activa para los tests de datos).
    settings.API_LECTURA_PUBLICA = False


def entrar(correo=CORREO_PRUEBA, clave=CLAVE_PRUEBA, **extra):
    return APIClient(**extra).post(LOGIN, {"email": correo, "password": clave}, format="json")


def con_bearer(token):
    return APIClient(HTTP_AUTHORIZATION=f"Bearer {token}")


# --- login ----------------------------------------------------------------------------------


def test_login_correcto_entrega_tokens_y_la_cuenta(usuario):
    respuesta = entrar()

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert set(datos) == {"access", "refresh", "usuario"}
    assert datos["usuario"] == {
        "id": usuario.pk,
        "nombre": CORREO_PRUEBA,
        "email": CORREO_PRUEBA,
        "rol": "editor",
    }
    assert con_bearer(datos["access"]).get(YO).json()["email"] == CORREO_PRUEBA
    usuario.refresh_from_db()
    assert usuario.last_login is not None


def test_el_correo_no_distingue_mayusculas_ni_espacios(usuario):
    assert entrar(correo="  Analista@VIGNO.cl ").status_code == 200


def test_los_tokens_duran_15_minutos_y_8_horas(usuario):
    datos = entrar().json()

    acceso, refresco = AccessToken(datos["access"]), RefreshToken(datos["refresh"])
    assert acceso["exp"] - acceso["iat"] == 15 * 60
    assert refresco["exp"] - refresco["iat"] == 8 * 60 * 60


def test_superusuario_tiene_rol_administrador(usuario, cliente_con_token):
    usuario.is_superuser = True
    usuario.save()

    assert entrar().json()["usuario"]["rol"] == "administrador"
    assert cliente_con_token.get(YO).json()["rol"] == "administrador"


def test_usuario_sin_grupo_tiene_rol_null(usuario, cliente_con_token):
    # Sin grupo de rol y sin ser superusuario, la cuenta no tiene rol.
    usuario.groups.clear()
    usuario.is_staff = True  # staff sin ser superusuario no basta
    usuario.save()

    assert entrar().json()["usuario"]["rol"] is None
    assert cliente_con_token.get(YO).json()["rol"] is None


@pytest.mark.parametrize(
    "correo,clave",
    [
        (CORREO_PRUEBA, "clave-equivocada"),
        ("nadie@vigno.cl", CLAVE_PRUEBA),
    ],
)
def test_clave_incorrecta_o_correo_inexistente_dan_la_misma_respuesta(usuario, correo, clave):
    respuesta = entrar(correo=correo, clave=clave)

    assert respuesta.status_code == 401
    assert respuesta.json() == {"detail": "Correo o contraseña incorrectos."}
    assert "access" not in respuesta.json()


def test_cuenta_desactivada_no_entra_y_responde_igual(usuario):
    usuario.is_active = False
    usuario.save()

    respuesta = entrar()

    assert respuesta.status_code == 401
    assert respuesta.json()["detail"] == "Correo o contraseña incorrectos."


def test_no_se_entra_con_el_nombre_de_usuario_en_vez_del_correo(django_user_model):
    django_user_model.objects.create_user(
        username="admin", email="admin@vigno.cl", password=CLAVE_PRUEBA
    )

    assert entrar(correo="admin@vigno.cl").status_code == 200
    # el campo exige un correo: "admin" no sirve aunque sea el username
    assert entrar(correo="admin").status_code == 400


def test_un_token_vencido_en_la_cabecera_no_impide_entrar(usuario):
    vencido = AccessToken.for_user(usuario)
    vencido.set_exp(lifetime=-timedelta(minutes=1))

    assert entrar(HTTP_AUTHORIZATION=f"Bearer {vencido}").status_code == 200


# --- tokens inválidos -------------------------------------------------------------------------


def test_token_vencido_da_401(usuario):
    vencido = AccessToken.for_user(usuario)
    vencido.set_exp(lifetime=-timedelta(seconds=1))

    assert con_bearer(vencido).get(YO).status_code == 401


def test_token_alterado_da_401(usuario):
    token = str(AccessToken.for_user(usuario))
    cabecera, cuerpo, firma = token.split(".")
    otra_firma = ("A" if firma[0] != "A" else "B") + firma[1:]

    assert con_bearer(f"{cabecera}.{cuerpo}.{otra_firma}").get(YO).status_code == 401


def test_token_firmado_con_otra_clave_da_401(usuario, settings):
    import jwt

    falso = jwt.encode(
        {"token_type": "access", "user_id": str(usuario.pk), "exp": 4102444800, "jti": "x"},
        "otra-clave-cualquiera-de-mas-de-32-bytes-de-largo",
        algorithm="HS256",
    )

    assert con_bearer(falso).get(YO).status_code == 401


def test_el_refresco_no_sirve_como_acceso(usuario):
    assert con_bearer(RefreshToken.for_user(usuario)).get(YO).status_code == 401


# --- refresco -----------------------------------------------------------------------------------


def test_refresco_entrega_tokens_nuevos_y_rota(usuario):
    refresco = entrar().json()["refresh"]

    respuesta = APIClient().post(REFRESH, {"refresh": refresco}, format="json")

    assert respuesta.status_code == 200
    nuevo = respuesta.json()
    assert set(nuevo) == {"access", "refresh"}
    assert nuevo["refresh"] != refresco
    assert con_bearer(nuevo["access"]).get(YO).status_code == 200
    # el refresco usado queda en la lista negra
    assert APIClient().post(REFRESH, {"refresh": refresco}, format="json").status_code == 401


def test_refresco_de_una_cuenta_borrada_da_401_y_no_500(usuario):
    # El token se emite sin pasar por el login: un login deja la cuenta en la bitácora
    # y una cuenta con historial no se puede borrar, solo desactivar.
    refresco = str(RefreshToken.for_user(usuario))
    usuario.delete()

    assert APIClient().post(REFRESH, {"refresh": refresco}, format="json").status_code == 401


def test_refresco_de_una_cuenta_desactivada_da_401(usuario):
    refresco = entrar().json()["refresh"]
    usuario.is_active = False
    usuario.save()

    assert APIClient().post(REFRESH, {"refresh": refresco}, format="json").status_code == 401


def test_refresco_alterado_da_401(usuario):
    refresco = entrar().json()["refresh"]

    respuesta = APIClient().post(REFRESH, {"refresh": refresco[:-3] + "abc"}, format="json")

    assert respuesta.status_code == 401


# --- cierre de sesión ---------------------------------------------------------------------------


def test_cerrar_sesion_invalida_el_refresco(usuario):
    tokens = entrar().json()
    cliente = con_bearer(tokens["access"])

    assert cliente.post(LOGOUT, {"refresh": tokens["refresh"]}, format="json").status_code == 204
    respuesta = APIClient().post(REFRESH, {"refresh": tokens["refresh"]}, format="json")
    assert respuesta.status_code == 401


def test_cerrar_sesion_pide_token(usuario):
    tokens = entrar().json()

    assert (
        APIClient().post(LOGOUT, {"refresh": tokens["refresh"]}, format="json").status_code == 401
    )


def test_no_se_puede_cerrar_la_sesion_de_otra_cuenta(usuario, django_user_model):
    otra = django_user_model.objects.create_user(
        username="otra@vigno.cl", email="otra@vigno.cl", password=CLAVE_PRUEBA
    )
    refresco_ajeno = str(RefreshToken.for_user(otra))

    respuesta = cliente_de(usuario).post(LOGOUT, {"refresh": refresco_ajeno}, format="json")

    assert respuesta.status_code == 400
    assert APIClient().post(REFRESH, {"refresh": refresco_ajeno}, format="json").status_code == 200


# --- límite de intentos ---------------------------------------------------------------------------


def test_sexto_intento_en_un_minuto_da_429(usuario):
    for _ in range(5):
        assert entrar(clave="mala").status_code == 401

    respuesta = entrar()  # ni con la clave correcta

    assert respuesta.status_code == 429


def test_el_limite_usa_la_ip_real_detras_de_nginx(usuario, settings):
    # nginx agrega la IP real al final de X-Forwarded-For; lo que escriba el cliente antes no
    # cuenta, así que cambiar esa parte no salta el límite.
    settings.REST_FRAMEWORK = {**settings.REST_FRAMEWORK, "NUM_PROXIES": 1}
    for i in range(5):
        entrar(clave="mala", HTTP_X_FORWARDED_FOR=f"10.0.0.{i}, 200.1.1.1")

    assert entrar(HTTP_X_FORWARDED_FOR="10.9.9.9, 200.1.1.1").status_code == 429
    assert entrar(HTTP_X_FORWARDED_FOR="10.0.0.1, 200.2.2.2").status_code == 200


def test_cambiar_clave_tambien_tiene_limite(cliente_con_token):
    for _ in range(5):
        cliente_con_token.post(
            CAMBIAR, {"clave_actual": "mala", "clave_nueva": NUEVA_CLAVE}, format="json"
        )

    respuesta = cliente_con_token.post(
        CAMBIAR, {"clave_actual": CLAVE_PRUEBA, "clave_nueva": NUEVA_CLAVE}, format="json"
    )

    assert respuesta.status_code == 429


# --- yo y cambiar clave ---------------------------------------------------------------------------


def test_yo_devuelve_la_cuenta_del_token(cliente_con_token, usuario):
    assert cliente_con_token.get(YO).json()["id"] == usuario.pk
    assert APIClient().get(YO).status_code == 401


def test_cambiar_clave_cierra_las_otras_sesiones_y_entrega_tokens_nuevos(usuario):
    tokens = entrar().json()
    cliente = con_bearer(tokens["access"])

    respuesta = cliente.post(
        CAMBIAR, {"clave_actual": CLAVE_PRUEBA, "clave_nueva": NUEVA_CLAVE}, format="json"
    )

    assert respuesta.status_code == 200
    nuevos = respuesta.json()
    # el acceso y el refresco anteriores ya no sirven
    assert cliente.get(YO).status_code == 401
    assert (
        APIClient().post(REFRESH, {"refresh": tokens["refresh"]}, format="json").status_code == 401
    )
    # los nuevos sí, y se entra con la clave nueva
    assert con_bearer(nuevos["access"]).get(YO).status_code == 200
    assert entrar(clave=CLAVE_PRUEBA).status_code == 401
    assert entrar(clave=NUEVA_CLAVE).status_code == 200


@pytest.mark.parametrize(
    "actual,nueva,campo",
    [
        ("mala", NUEVA_CLAVE, "clave_actual"),
        (CLAVE_PRUEBA, CLAVE_PRUEBA, "clave_nueva"),
        (CLAVE_PRUEBA, "corta", "clave_nueva"),
        (CLAVE_PRUEBA, "12345678901", "clave_nueva"),
        (CLAVE_PRUEBA, "password123", "clave_nueva"),
    ],
)
def test_cambiar_clave_rechaza_actual_incorrecta_o_nueva_debil(
    cliente_con_token, usuario, actual, nueva, campo
):
    respuesta = cliente_con_token.post(
        CAMBIAR, {"clave_actual": actual, "clave_nueva": nueva}, format="json"
    )

    assert respuesta.status_code == 400
    assert campo in respuesta.json()
    usuario.refresh_from_db()
    assert usuario.check_password(CLAVE_PRUEBA)


# --- todo pide token salvo health, login y refresco -----------------------------------------------


def rutas_api():
    def recorrer(patrones, prefijo=""):
        for patron in patrones:
            if isinstance(patron, URLResolver):
                yield from recorrer(patron.url_patterns, prefijo + str(patron.pattern))
            elif isinstance(patron, URLPattern):
                yield prefijo + str(patron.pattern)

    for ruta in recorrer(get_resolver().url_patterns):
        if ruta.startswith("api/v1/"):
            yield "/" + ruta.replace("<int:pk>", "1").replace("<str:temporada>", "2024-2025")


PUBLICAS = {"/api/v1/auth/token", "/api/v1/auth/refresh"}


def test_hay_rutas_para_revisar():
    rutas = set(rutas_api())
    assert {"/api/v1/datos", "/api/v1/cargas", "/api/v1/auth/yo"} <= rutas


@pytest.mark.parametrize("ruta", sorted(set(rutas_api()) - PUBLICAS))
@pytest.mark.parametrize("metodo", ["get", "post"])
def test_sin_token_todo_responde_401(ruta, metodo):
    respuesta = getattr(APIClient(), metodo)(ruta, {}, format="json")

    assert respuesta.status_code == 401, (metodo, ruta, respuesta.status_code)


def test_health_login_y_refresco_no_piden_token(usuario):
    assert APIClient().get("/api/health/").status_code == 200
    assert entrar().status_code == 200
    respuesta = APIClient().post(REFRESH, {"refresh": "x"}, format="json")
    assert respuesta.status_code == 401
    assert respuesta.json()["code"] == "token_not_valid"  # revisó el refresco, no pidió login


def test_lectura_publica_abre_solo_las_lecturas_del_dashboard(settings, usuario):
    settings.API_LECTURA_PUBLICA = True
    cliente = APIClient()

    assert cliente.get("/api/v1/estaciones").status_code == 200
    assert cliente.get("/api/v1/temporadas").status_code == 200
    for privada in ("/api/v1/cargas", "/api/v1/correcciones", YO):
        assert cliente.get(privada).status_code == 401, privada
    assert cliente.post("/api/v1/estaciones", {}, format="json").status_code == 401


def test_api_lectura_publica_es_false_por_defecto():
    from vigno.settings import base

    assert base.config("API_LECTURA_PUBLICA_NO_DEFINIDA", default=False, cast=bool) is False
    assert (
        "default=False"
        in open(base.__file__, encoding="utf-8")
        .read()
        .split("API_LECTURA_PUBLICA = config(")[1]
        .split("\n")[0]
    )


# --- X-Api-Key retirada y esquema Bearer -----------------------------------------------------------


def test_x_api_key_ya_no_existe(settings):
    from pathlib import Path

    assert not hasattr(settings, "INGESTA_API_KEY")
    assert not Path(settings.BASE_DIR, "apps", "ingesta", "autenticacion.py").exists()
    respuesta = APIClient(HTTP_X_API_KEY="cualquiera").get("/api/v1/cargas")
    assert respuesta.status_code == 401


def test_openapi_tiene_esquema_bearer():
    esquema = SchemaGenerator().get_schema(public=True)

    esquemas = esquema["components"]["securitySchemes"]
    assert {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}.items() <= next(
        iter(esquemas.values())
    ).items()
    assert "ingestaApiKey" not in esquemas


# --- correo único y primer administrador ------------------------------------------------------------


def test_el_correo_es_unico_sin_distinguir_mayusculas(usuario, django_user_model):
    with pytest.raises(IntegrityError), transaction.atomic():
        django_user_model.objects.create_user(username="otra", email="ANALISTA@vigno.cl")
    # las cuentas sin correo no chocan entre sí
    django_user_model.objects.create_user(username="sin-correo-1", email="")
    django_user_model.objects.create_user(username="sin-correo-2", email="")


def test_crear_admin_inicial_desde_variables(monkeypatch):
    monkeypatch.setenv("DJANGO_SUPERUSER_EMAIL", "Jefa@Vigno.cl")
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "Admin-inicial-2026")

    call_command("crear_admin_inicial")
    call_command("crear_admin_inicial")  # no duplica

    admin = User.objects.get(email="jefa@vigno.cl")
    assert admin.is_superuser and admin.is_staff
    assert entrar(correo="jefa@vigno.cl", clave="Admin-inicial-2026").status_code == 200


def test_crear_admin_inicial_no_pisa_una_clave_cambiada(monkeypatch, usuario):
    monkeypatch.setenv("DJANGO_SUPERUSER_EMAIL", CORREO_PRUEBA)
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "Otra-clave-larga-2026")

    call_command("crear_admin_inicial")

    usuario.refresh_from_db()
    assert usuario.check_password(CLAVE_PRUEBA)


def test_crear_admin_inicial_rechaza_clave_debil(monkeypatch):
    monkeypatch.setenv("DJANGO_SUPERUSER_EMAIL", "jefa@vigno.cl")
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "12345678")

    with pytest.raises(CommandError, match="no cumple las reglas"):
        call_command("crear_admin_inicial")
    assert not User.objects.filter(email="jefa@vigno.cl").exists()


def test_crear_admin_inicial_sin_variables_no_hace_nada(monkeypatch):
    monkeypatch.delenv("DJANGO_SUPERUSER_EMAIL", raising=False)
    monkeypatch.delenv("DJANGO_SUPERUSER_PASSWORD", raising=False)

    call_command("crear_admin_inicial")

    assert not User.objects.exists()


# --- clave de firma de los tokens -------------------------------------------------------------------


@pytest.mark.parametrize(
    "clave,arranca",
    [
        ("corta", False),
        ("REEMPLAZAR_POR_UNA_CLAVE_LARGA_ALEATORIA_que_alcanza_los_cincuenta", False),
        ("k" * 20 + "una-clave-aleatoria-de-produccion-larga", True),
    ],
)
def test_produccion_no_arranca_con_una_secret_key_debil(clave, arranca):
    import os
    import subprocess
    import sys

    from django.conf import settings

    entorno = {
        **os.environ,
        "SECRET_KEY": clave,
        "DJANGO_SETTINGS_MODULE": "vigno.settings.production",
    }
    resultado = subprocess.run(
        [sys.executable, "-c", "import django; django.setup()"],
        cwd=settings.BASE_DIR,
        env=entorno,
        capture_output=True,
        text=True,
    )

    assert (resultado.returncode == 0) is arranca, resultado.stderr[-300:]
    if not arranca:
        assert "SECRET_KEY debe tener al menos 50 caracteres" in resultado.stderr
