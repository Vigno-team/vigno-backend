"""E1C-127: `exportar_json` entrega el bloque `mapa_calor` a partir de CapaSatelital (E1C-126)."""

import json
from datetime import date

import pytest
from django.core.management import call_command

from apps.clima.mapa_calor import (
    MOTIVO_INCOMPLETA,
    MOTIVO_SIN_IMAGEN,
    MOTIVO_SIN_UBICACION,
    bloque_mapa_calor,
)
from apps.clima.models import CapaSatelital, Estacion
from apps.clima.tests.test_contrato_mapa_calor import validar_entrada

pytestmark = pytest.mark.django_db

SAN_CLEMENTE = "cp-san-clemente-01"
EL_ARENAL = "cp-villavicencio-01"


@pytest.fixture
def san_clemente():
    # Las migraciones ya dejan las dos estaciones reales; la ubicación la carga cargar_areas_mapa.
    estacion = Estacion.objects.get(codigo=SAN_CLEMENTE)
    estacion.latitud, estacion.longitud = -35.516667, -71.466667
    estacion.save(update_fields=["latitud", "longitud"])
    return estacion


def crear_capa(estacion, fecha, **cambios):
    datos = {
        "estacion": estacion,
        "capa": "ndvi",
        "fecha_imagen": fecha,
        "limites": [300000.0, 6069980.0, 300030.0, 6070020.0],
        "limites_latlon": [-71.4719, -35.5195, -71.4641, -35.5128],
        "crs": "EPSG:32719",
        "ancho": 3,
        "alto": 2,
        "resolucion_m": 10.0,
        "valores": [[0.41234, None, 0.9], [None, -0.2, 0.55555]],
        "porcentaje_validos": 80.0,
        "nubosidad_pct": 5.5,
        "version": "ndvi-sentinel-2-l2a-v1_scl-cloud-shadow_10m",
    }
    datos.update(cambios)
    return CapaSatelital.objects.create(**datos)


def exportar(tmp_path):
    salida = tmp_path / "datos.json"
    call_command("exportar_json", "--salida", str(salida), "--sobrescribir")
    return json.loads(salida.read_text(encoding="utf-8"))


def entrada(datos, codigo):
    return next(e for e in datos["mapa_calor"] if e["estacion_id"] == codigo)


def test_una_entrada_por_estacion_en_el_mismo_orden_y_con_la_forma_del_contrato(
    tmp_path, san_clemente
):
    crear_capa(san_clemente, date(2026, 10, 17))

    datos = exportar(tmp_path)

    assert [e["estacion_id"] for e in datos["mapa_calor"]] == [e["id"] for e in datos["estaciones"]]
    nombres = {e["id"]: e["nombre"] for e in datos["estaciones"]}
    for item in datos["mapa_calor"]:
        assert item["nombre"] == nombres[item["estacion_id"]]
        validar_entrada(item)
    assert datos["mapa_calor"] == json.loads(json.dumps(bloque_mapa_calor()))


def test_entrega_los_datos_de_la_capa_guardada(tmp_path, san_clemente):
    crear_capa(san_clemente, date(2026, 10, 17))

    item = entrada(exportar(tmp_path), SAN_CLEMENTE)

    assert item["fecha_imagen"] == "2026-10-17"
    assert item["limites"] == [[-35.5195, -71.4719], [-35.5128, -71.4641]]
    assert item["valores"] == [[0.412, None, 0.9], [None, -0.2, 0.556]]
    assert (item["ancho"], item["alto"], item["resolucion_m"]) == (3, 2, 10.0)
    assert (item["pct_validos"], item["nubosidad_pct"]) == (80.0, 5.5)
    assert item["atribucion"] == "Contains modified Copernicus Sentinel data 2026"
    assert "motivo_nulo" not in item


def test_entrega_la_imagen_mas_reciente(tmp_path, san_clemente):
    crear_capa(san_clemente, date(2026, 10, 10), porcentaje_validos=60.0)
    crear_capa(san_clemente, date(2026, 10, 17), porcentaje_validos=80.0)
    crear_capa(san_clemente, date(2026, 9, 30), porcentaje_validos=90.0)

    item = entrada(exportar(tmp_path), SAN_CLEMENTE)

    assert item["fecha_imagen"] == "2026-10-17"
    assert item["pct_validos"] == 80.0


def test_salta_las_imagenes_sin_celdas_validas(tmp_path, san_clemente):
    crear_capa(san_clemente, date(2026, 10, 10), porcentaje_validos=60.0)
    crear_capa(san_clemente, date(2026, 10, 17), porcentaje_validos=0.0, valores=[[None] * 3] * 2)

    assert entrada(exportar(tmp_path), SAN_CLEMENTE)["fecha_imagen"] == "2026-10-10"

    CapaSatelital.objects.filter(fecha_imagen=date(2026, 10, 10)).delete()
    item = entrada(exportar(tmp_path), SAN_CLEMENTE)
    assert item["motivo_nulo"] == MOTIVO_SIN_IMAGEN and item["valores"] is None


def test_la_capa_de_una_estacion_no_aparece_en_otra(tmp_path, san_clemente):
    crear_capa(san_clemente, date(2026, 10, 17))

    arenal = entrada(exportar(tmp_path), EL_ARENAL)

    assert arenal["valores"] is None
    assert arenal["motivo_nulo"] == MOTIVO_SIN_UBICACION  # sin longitud ni contorno cargado


def test_con_ubicacion_pero_sin_imagen_dice_que_falta_la_imagen(tmp_path, san_clemente):
    assert entrada(exportar(tmp_path), SAN_CLEMENTE)["motivo_nulo"] == MOTIVO_SIN_IMAGEN


def test_una_capa_sin_limites_latlon_no_se_pinta(tmp_path, san_clemente):
    crear_capa(san_clemente, date(2026, 10, 17), limites_latlon=None)

    item = entrada(exportar(tmp_path), SAN_CLEMENTE)

    validar_entrada(item)
    assert item["motivo_nulo"] == MOTIVO_INCOMPLETA
