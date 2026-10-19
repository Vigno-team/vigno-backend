import json
from datetime import date
from unittest.mock import Mock, patch

import numpy as np
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from rasterio.io import MemoryFile
from rasterio.transform import from_origin

from apps.clima.models import CapaSatelital, Estacion
from apps.clima.satelite import (
    CATALOG_URL,
    COLECCION,
    EVALSCRIPT_NDVI,
    PROCESS_URL,
    TOKEN_URL,
    ErrorSatelite,
    GrillaNDVI,
    _leer_geotiff,
    _seleccionar_escena,
    _token,
    obtener_grilla_ndvi,
)


def crear_geotiff(valores=None):
    valores = valores or [[0.4, -9999], [float("nan"), -0.2]]
    with MemoryFile() as archivo:
        with archivo.open(
            driver="GTiff",
            width=2,
            height=2,
            count=1,
            dtype="float32",
            crs="EPSG:32719",
            transform=from_origin(300000, 6070000, 10, 10),
            nodata=-9999,
        ) as dataset:
            dataset.write(np.asarray(valores, dtype="float32"), 1)
        return archivo.read()


def geometria_prueba():
    return {
        "type": "Polygon",
        "coordinates": [[[-71.47, -35.51], [-71.46, -35.51], [-71.46, -35.52], [-71.47, -35.51]]],
    }


def respuesta(status=200, json_data=None, content=b""):
    mock = Mock()
    mock.status_code = status
    mock.json.return_value = json_data or {}
    mock.content = content
    mock.raise_for_status.return_value = None
    return mock


def test_catalogo_selecciona_la_escena_menos_nublada_de_30_dias():
    mock = respuesta(
        json_data={
            "features": [
                {
                    "properties": {
                        "datetime": "2026-10-17T14:00:00Z",
                        "eo:cloud_cover": 5.5,
                    }
                },
                {
                    "properties": {
                        "datetime": "2026-10-18T14:00:00Z",
                        "eo:cloud_cover": 20.0,
                    }
                },
                {
                    "properties": {
                        "datetime": "2026-09-18T14:00:00Z",
                        "eo:cloud_cover": 0.0,
                    }
                },
            ]
        }
    )
    with patch("apps.clima.satelite.requests.post", return_value=mock) as post:
        fecha, nubes = _seleccionar_escena(geometria_prueba(), "token-test", date(2026, 10, 18))

    assert (fecha, nubes) == (date(2026, 10, 17), 5.5)
    llamada = post.call_args
    assert llamada.args[0] == CATALOG_URL
    assert llamada.kwargs["json"]["collections"] == [COLECCION]
    assert llamada.kwargs["json"]["intersects"] == geometria_prueba()
    assert llamada.kwargs["json"]["datetime"].startswith("2026-09-19T00:00:00")


def test_geotiff_se_convierte_en_grilla_norte_a_sur_con_nodata():
    grilla = _leer_geotiff(crear_geotiff(), date(2026, 10, 17), 5.5)

    assert grilla.fecha_imagen == date(2026, 10, 17)
    assert (grilla.ancho, grilla.alto) == (2, 2)
    assert grilla.resolucion_m == 10
    assert grilla.crs == "EPSG:32719"
    assert len(grilla.limites_latlon) == 4
    assert grilla.limites_latlon[0] < grilla.limites_latlon[2]
    assert grilla.valores[0][0] == pytest.approx(0.4)
    assert grilla.valores[0][1] is None
    assert grilla.valores[1][0] is None
    assert grilla.valores[1][1] == pytest.approx(-0.2)
    assert grilla.porcentaje_validos == 50
    assert grilla.nubosidad_pct == 5.5


def test_proceso_simulado_autentica_busca_escena_y_guarda_ndvi():
    respuestas = [
        respuesta(json_data={"access_token": "token-test"}),
        respuesta(
            json_data={
                "features": [
                    {
                        "properties": {
                            "datetime": "2026-10-17T14:00:00Z",
                            "eo:cloud_cover": 5.5,
                        }
                    }
                ]
            }
        ),
        respuesta(content=crear_geotiff()),
    ]
    with patch("apps.clima.satelite.requests.post", side_effect=respuestas) as post:
        grilla = obtener_grilla_ndvi(
            geometria_prueba(),
            hoy=date(2026, 10, 18),
            client_id="id-test",
            client_secret="secret-test",
        )

    assert [llamada.args[0] for llamada in post.call_args_list] == [
        TOKEN_URL,
        CATALOG_URL,
        PROCESS_URL,
    ]
    auth_data = post.call_args_list[0].kwargs["data"]
    assert auth_data == {
        "grant_type": "client_credentials",
        "client_id": "id-test",
        "client_secret": "secret-test",
    }
    request_data = json.loads(post.call_args_list[2].kwargs["files"]["request"][1])
    assert request_data["input"]["data"][0]["type"] == "sentinel-2-l2a"
    assert request_data["input"]["data"][0]["dataFilter"]["timeRange"] == {
        "from": "2026-10-17T00:00:00+00:00",
        "to": "2026-10-17T23:59:59+00:00",
    }
    assert request_data["input"]["bounds"]["properties"]["crs"].endswith("/32719")
    assert request_data["output"]["resx"] == request_data["output"]["resy"] == 10
    assert post.call_args_list[2].kwargs["files"]["evalscript"][1] == EVALSCRIPT_NDVI
    assert grilla.fecha_imagen == date(2026, 10, 17)
    assert grilla.valores[0][0] == pytest.approx(0.4)
    assert grilla.valores[0][1] is None
    assert grilla.valores[1][0] is None
    assert grilla.valores[1][1] == pytest.approx(-0.2)


@pytest.mark.django_db
def test_comando_persiste_grilla_de_san_clemente_y_actualiza_idempotente():
    estacion = Estacion.objects.get(codigo="cp-san-clemente-01")
    grilla = GrillaNDVI(
        fecha_imagen=date(2026, 10, 17),
        limites=[300000, 6069980, 300020, 6070000],
        limites_latlon=[-71.204886, -35.493616, -71.204661, -35.493432],
        crs="EPSG:32719",
        ancho=2,
        alto=2,
        resolucion_m=10,
        valores=[[0.4, None], [None, -0.2]],
        porcentaje_validos=50,
        nubosidad_pct=5.5,
    )
    with patch("apps.clima.satelite.obtener_grilla_ndvi", return_value=grilla):
        call_command("actualizar_mapa_calor", estacion=estacion.codigo, capa="ndvi")
        call_command("actualizar_mapa_calor", estacion=estacion.codigo, capa="ndvi")

    capa = CapaSatelital.objects.get(estacion=estacion, capa="ndvi")
    assert CapaSatelital.objects.filter(estacion=estacion).count() == 1
    assert capa.fecha_imagen == date(2026, 10, 17)
    assert capa.limites_latlon == [-71.204886, -35.493616, -71.204661, -35.493432]
    assert capa.valores[0][0] == pytest.approx(0.4)
    assert capa.valores[1][1] == pytest.approx(-0.2)
    assert capa.porcentaje_validos == 50


@pytest.mark.django_db
def test_comando_predio_sin_contorno_falla_sin_llamar_api():
    estacion = Estacion.objects.get(codigo="cp-villavicencio-01")
    with patch("apps.clima.satelite.requests.post") as post:
        with pytest.raises(CommandError, match="No existe el predio cp-villavicencio-01"):
            call_command("actualizar_mapa_calor", estacion=estacion.codigo, capa="ndvi")
    post.assert_not_called()


def test_scl_enmascara_sombra_y_clases_de_nube():
    assert "[0, 1, 3, 7, 8, 9, 10, 11]" in EVALSCRIPT_NDVI
    assert 'sampleType: "FLOAT32"' in EVALSCRIPT_NDVI
    assert "sample.B08 - sample.B04" in EVALSCRIPT_NDVI


def test_token_falla_cuando_el_servidor_devuelve_error_http():
    import requests

    mock_error = Mock()
    mock_error.raise_for_status.side_effect = requests.RequestException("401 Unauthorized")
    with patch("apps.clima.satelite.requests.post", return_value=mock_error):
        with pytest.raises(ErrorSatelite, match="Error al autenticar"):
            _token("id-malo", "secret-malo")


def test_token_falla_cuando_no_hay_access_token_en_la_respuesta():
    mock_ok = respuesta(json_data={"expires_in": 3600})  # sin access_token
    with patch("apps.clima.satelite.requests.post", return_value=mock_ok):
        with pytest.raises(ErrorSatelite, match="access_token"):
            _token("id-test", "secret-test")


def test_catalog_falla_cuando_no_hay_escenas_validas_en_el_rango():
    mock = respuesta(
        json_data={
            "features": [
                {
                    "properties": {
                        "datetime": "2020-01-01T00:00:00Z",
                        "eo:cloud_cover": 0.0,
                    }
                }
            ]
        }
    )
    with patch("apps.clima.satelite.requests.post", return_value=mock):
        with pytest.raises(ErrorSatelite, match="No hay escenas"):
            _seleccionar_escena(geometria_prueba(), "token-test", date(2026, 10, 18))


def test_catalog_falla_cuando_la_respuesta_http_es_error():
    import requests

    mock_error = Mock()
    mock_error.raise_for_status.side_effect = requests.RequestException("500 Server Error")
    with patch("apps.clima.satelite.requests.post", return_value=mock_error):
        with pytest.raises(ErrorSatelite, match="Error al consultar el catálogo"):
            _seleccionar_escena(geometria_prueba(), "token-test", date(2026, 10, 18))


def test_process_falla_cuando_el_servidor_devuelve_error_http():
    import requests

    respuestas = [
        respuesta(json_data={"access_token": "token-test"}),
        respuesta(
            json_data={
                "features": [
                    {
                        "properties": {
                            "datetime": "2026-10-17T14:00:00Z",
                            "eo:cloud_cover": 5.5,
                        }
                    }
                ]
            }
        ),
        Mock(
            **{
                "raise_for_status.side_effect": requests.RequestException("503 Service Unavailable"),
                "status_code": 503,
            }
        ),
    ]
    with patch("apps.clima.satelite.requests.post", side_effect=respuestas):
        with pytest.raises(ErrorSatelite, match="Error al solicitar el GeoTIFF"):
            obtener_grilla_ndvi(
                geometria_prueba(),
                hoy=date(2026, 10, 18),
                client_id="id-test",
                client_secret="secret-test",
            )

