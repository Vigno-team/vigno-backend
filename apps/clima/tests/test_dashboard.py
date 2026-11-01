"""E1C-93: contrato agregado, validación HTTP y publicación inicial."""

import json
from contextlib import contextmanager
from datetime import date

import pytest
from django.db import OperationalError
from drf_spectacular.generators import SchemaGenerator
from rest_framework.test import APIClient

from apps.clima import datos_frontend
from apps.clima.archivos import escribir_json_atomico
from apps.clima.management.commands.exportar_json import exportar
from apps.clima.models import Estacion, ResumenDiario


@pytest.fixture
def entorno(settings, tmp_path):
    settings.BASE_DIR = tmp_path
    settings.DATOS_DIR = tmp_path / "publicados"
    config = tmp_path / "config"
    config.mkdir()
    (config / "areas_mapa.json").write_text('{"type":"FeatureCollection","features":[]}')
    return settings.DATOS_DIR / "vigno-datos-reales.json"


@pytest.mark.django_db
def test_datos_sin_archivo_exporta_guarda_y_conserva_contrato(entorno, monkeypatch):
    estacion = Estacion.objects.create(nombre="Dashboard", codigo="dashboard", latitud=-35.5)
    ResumenDiario.objects.create(
        estacion=estacion,
        fecha=date(2025, 1, 10),
        temporada="2024-2025",
        tmax=30,
        tmin=12,
        tmedia=21,
        precipitacion=0,
        corregido_a_mano=True,
    )
    esperado = exportar()
    llamadas = []

    def exportacion():
        llamadas.append(True)
        datos = exportar()
        # El instante de la exportación no es el dato climático que se está comparando.
        datos["generado"] = esperado["generado"]
        return datos

    monkeypatch.setattr(datos_frontend, "exportar", exportacion)
    respuesta = APIClient().get("/api/v1/datos")
    assert respuesta.status_code == 200
    assert respuesta.json() == esperado
    assert json.loads(entorno.read_text(encoding="utf-8")) == esperado
    assert respuesta["Cache-Control"] == "no-cache"
    assert APIClient().get("/api/v1/datos").json() == esperado
    assert len(llamadas) == 1
    assert not list(entorno.parent.glob("*.tmp"))


def test_datos_existentes_no_consultan_base_ni_recalculan(entorno, monkeypatch):
    datos = {"generado": "2026-10-30T12:00:00-03:00", "estaciones": []}
    escribir_json_atomico(entorno, datos)

    def prohibido():
        pytest.fail("El archivo existente se debe servir sin exportar ni adquirir candado")

    monkeypatch.setattr(datos_frontend, "exportar", prohibido)
    monkeypatch.setattr(datos_frontend, "candado", prohibido)
    assert APIClient().get("/api/v1/datos").json() == datos


def test_primera_publicacion_relee_bajo_el_candado(entorno, monkeypatch):
    datos = {"generado": "publicado-por-actualizar-todo", "estaciones": []}

    @contextmanager
    def otro_publica():
        escribir_json_atomico(entorno, datos)
        yield

    monkeypatch.setattr(datos_frontend, "candado", otro_publica)
    monkeypatch.setattr(datos_frontend, "exportar", lambda: pytest.fail("No sobrescribir"))
    assert APIClient().get("/api/v1/datos").json() == datos


@pytest.mark.parametrize("variante", ["identico", "fuerte", "lista", "asterisco"])
def test_etag_devuelve_304_sin_cuerpo(entorno, variante):
    escribir_json_atomico(entorno, {"generado": "2026-10-30T12:00:00-03:00", "estaciones": []})
    cliente = APIClient()
    tag = cliente.get("/api/v1/datos")["ETag"]
    candidato = {
        "identico": tag,
        "fuerte": tag.removeprefix("W/"),
        "lista": '"otro", ' + tag,
        "asterisco": "*",
    }[variante]
    respuesta = cliente.get("/api/v1/datos", HTTP_IF_NONE_MATCH=candidato)
    assert respuesta.status_code == 304 and respuesta.content == b""
    assert respuesta["ETag"] == tag and respuesta["Cache-Control"] == "no-cache"


@pytest.mark.parametrize("cambio", [{"generado": "nuevo"}, {"valor": 2}])
def test_etag_cambia_por_generado_o_por_contenido_en_el_mismo_segundo(entorno, cambio):
    datos = {"generado": "2026-10-30T12:00:00-03:00", "valor": 1}
    escribir_json_atomico(entorno, datos)
    cliente = APIClient()
    tag = cliente.get("/api/v1/datos")["ETag"]
    datos.update(cambio)
    escribir_json_atomico(entorno, datos)
    respuesta = cliente.get("/api/v1/datos", HTTP_IF_NONE_MATCH=tag)
    assert respuesta.status_code == 200 and respuesta.json() == datos
    assert respuesta["ETag"] != tag


def test_head_conserva_cabeceras_y_no_entrega_cuerpo(entorno):
    escribir_json_atomico(entorno, {"generado": "version-1"})
    cliente = APIClient()
    tag = cliente.get("/api/v1/datos")["ETag"]
    respuesta = cliente.head("/api/v1/datos")
    assert respuesta.status_code == 200 and respuesta.content == b""
    assert respuesta["ETag"] == tag
    assert cliente.head("/api/v1/datos", HTTP_IF_NONE_MATCH=tag).status_code == 304


@pytest.mark.django_db
@pytest.mark.parametrize("error", [PermissionError("ruta privada"), OperationalError("bd privada")])
def test_error_al_publicar_responde_503_sin_filtrar_detalles(entorno, monkeypatch, error):
    def falla(*args):
        raise error

    monkeypatch.setattr(datos_frontend, "escribir_json_atomico", falla)
    respuesta = APIClient().get("/api/v1/datos")
    assert respuesta.status_code == 503 and respuesta["Cache-Control"] == "no-store"
    assert respuesta["Retry-After"] == "30"
    assert "privada" not in respuesta.content.decode()
    assert not entorno.exists()


@pytest.mark.parametrize("contenido", ["{incompleto", "[]", '{"dato": NaN}', '{"dato": Infinity}'])
@pytest.mark.parametrize(
    "endpoint,archivo",
    [
        ("datos", "publicados/vigno-datos-reales.json"),
        ("actualizacion", "publicados/actualizacion.json"),
        ("prediccion-ficticia", "data/ficticio/prediccion_ficticia.json"),
    ],
)
def test_archivo_invalido_no_se_sobrescribe(entorno, settings, endpoint, archivo, contenido):
    ruta = settings.BASE_DIR / archivo
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido, encoding="utf-8")
    respuesta = APIClient().get(f"/api/v1/{endpoint}")
    assert respuesta.status_code == 503
    assert ruta.read_text(encoding="utf-8") == contenido
    assert respuesta["Cache-Control"] == "no-store"


def test_prediccion_ausente_devuelve_motivo_y_no_crea_datos(entorno, settings):
    respuesta = APIClient().get("/api/v1/prediccion-ficticia")
    assert respuesta.status_code == 404
    assert respuesta.json() == {"motivo_nulo": "Aún no se ha entrenado el modelo de California."}
    assert respuesta["Cache-Control"] == "no-store"
    assert not (settings.BASE_DIR / "data/ficticio").exists()


def test_prediccion_devuelve_exactamente_el_archivo_de_e124(entorno, settings):
    datos = {
        "datos_ficticios": True,
        "fuente": "California",
        "modelo": {"metricas": {}},
        "predicciones": [],
    }
    escribir_json_atomico(settings.BASE_DIR / "data/ficticio/prediccion_ficticia.json", datos)
    respuesta = APIClient().get("/api/v1/prediccion-ficticia")
    assert respuesta.status_code == 200 and respuesta.json() == datos


def test_actualizacion_sin_archivo_es_generado_null_y_no_publica(entorno):
    respuesta = APIClient().get("/api/v1/actualizacion")
    assert respuesta.status_code == 200 and respuesta.json() == {"generado": None}
    assert respuesta["Cache-Control"] == "no-cache"
    assert not entorno.parent.exists()


def test_actualizacion_refleja_la_ultima_corrida_incluso_si_fallo(entorno):
    for ok in (True, False):
        datos = {
            "generado": f"version-{ok}",
            "ok": ok,
            "pasos": [
                {"paso": "exportar_json", "ok": ok, "segundos": 0.1, "detalle": ""},
            ],
        }
        escribir_json_atomico(entorno.parent / "actualizacion.json", datos)
        respuesta = APIClient().get("/api/v1/actualizacion")
        assert respuesta.status_code == 200 and respuesta.json() == datos


@pytest.mark.parametrize("endpoint", ["datos", "actualizacion", "prediccion-ficticia"])
def test_endpoints_publicos_no_permiten_escritura(endpoint):
    assert APIClient().post(f"/api/v1/{endpoint}", {}).status_code == 405


def test_cors_permite_vite_revalidar_y_leer_etag(entorno, settings):
    settings.CORS_ALLOWED_ORIGINS = ["http://localhost:5173"]
    escribir_json_atomico(entorno, {"generado": "version-1"})
    cliente = APIClient()
    respuesta = cliente.get("/api/v1/datos", HTTP_ORIGIN="http://localhost:5173")
    assert respuesta["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert "ETag" in respuesta["Access-Control-Expose-Headers"]
    preflight = cliente.options(
        "/api/v1/datos",
        HTTP_ORIGIN="http://localhost:5173",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="if-none-match",
    )
    assert preflight.status_code == 200
    assert "if-none-match" in preflight["Access-Control-Allow-Headers"]
    sin_cambios = cliente.get(
        "/api/v1/datos", HTTP_ORIGIN="http://localhost:5173", HTTP_IF_NONE_MATCH=respuesta["ETag"]
    )
    assert sin_cambios.status_code == 304
    assert sin_cambios["Access-Control-Allow-Origin"] == "http://localhost:5173"
    denegado = cliente.get("/api/v1/datos", HTTP_ORIGIN="https://otro.example")
    assert "Access-Control-Allow-Origin" not in denegado


def test_tres_endpoints_y_etag_estan_en_openapi_y_docs():
    schema = SchemaGenerator().get_schema(public=True)
    for endpoint in ("datos", "actualizacion", "prediccion-ficticia"):
        assert "get" in schema["paths"][f"/api/v1/{endpoint}"]
    datos = schema["paths"]["/api/v1/datos"]["get"]
    assert "304" in datos["responses"]
    assert "ETag" in datos["responses"]["200"]["headers"]
    assert "If-None-Match" in [p["name"] for p in datos["parameters"]]
    assert APIClient().get("/api/docs/").status_code == 200
