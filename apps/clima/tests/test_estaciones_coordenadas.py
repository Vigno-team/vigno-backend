"""E1C-127: latitud y longitud de las estaciones en la API y en el JSON exportado."""

import json

import pytest
from django.core.management import call_command

from apps.clima.models import Estacion

pytestmark = pytest.mark.django_db


@pytest.fixture
def estaciones_de_prueba():
    # Las migraciones ya dejan cargadas las estaciones reales: se usan códigos propios.
    Estacion.objects.create(
        nombre="Con coordenadas", codigo="coord-01", latitud=-35.516667, longitud=-71.466667
    )
    Estacion.objects.create(nombre="Sin longitud", codigo="coord-02", latitud=-35.52)
    Estacion.objects.create(nombre="Sin ubicación", codigo="coord-03")


def coordenadas(estaciones: list[dict], codigo: str) -> tuple:
    estacion = next(e for e in estaciones if e["id"] == codigo)
    return estacion["latitud"], estacion["longitud"]


def comprobar(estaciones: list[dict]) -> None:
    assert coordenadas(estaciones, "coord-01") == (-35.516667, -71.466667)
    assert coordenadas(estaciones, "coord-02") == (-35.52, None)
    assert coordenadas(estaciones, "coord-03") == (None, None)


def test_la_api_trae_latitud_y_longitud(client, estaciones_de_prueba):
    comprobar(client.get("/api/v1/estaciones").json())


def test_el_json_exportado_trae_latitud_y_longitud(tmp_path, estaciones_de_prueba):
    salida = tmp_path / "datos.json"

    call_command("exportar_json", "--salida", str(salida))

    comprobar(json.loads(salida.read_text(encoding="utf-8"))["estaciones"])
