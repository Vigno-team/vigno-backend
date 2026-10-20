"""E1C-127: forma del bloque `mapa_calor` y lo que arma `entrada_mapa_calor`.

No usa la base de datos. `validar_entrada` también se aplica a la salida real de
`exportar_json` en test_exportar_mapa_calor.py.
"""

import copy
import json
import math
import re
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from apps.clima.areas_mapa import AreasMapaError, validar_punto
from apps.clima.mapa_calor import (
    CAMPOS_DE_IMAGEN,
    ESCALA,
    FUENTE,
    MOTIVO_INCOMPLETA,
    MOTIVO_SIN_IMAGEN,
    MOTIVO_SIN_UBICACION,
    entrada_mapa_calor,
)

EJEMPLO = json.loads(
    (
        Path(__file__).resolve().parents[3] / "docs" / "contrato" / "ejemplo_mapa_calor.json"
    ).read_text(encoding="utf-8")
)

IDENTIFICACION = {"estacion_id", "capa"}
CLAVES = IDENTIFICACION | set(CAMPOS_DE_IMAGEN)
COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def es_numero(x) -> bool:
    return isinstance(x, int | float) and not isinstance(x, bool) and math.isfinite(x)


def es_entero(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool) and x > 0


def validar_entrada(entrada: dict) -> None:
    """Lanza AssertionError (o AreasMapaError) si la entrada no cumple el contrato."""
    if "motivo_nulo" in entrada:
        assert set(entrada) == CLAVES | {"motivo_nulo"}
        assert isinstance(entrada["motivo_nulo"], str) and entrada["motivo_nulo"]
        # sin imagen útil, todo lo demás va en null
        assert all(entrada[k] is None for k in CLAVES - IDENTIFICACION)
        return

    assert set(entrada) == CLAVES
    assert isinstance(entrada["estacion_id"], str) and entrada["capa"] == "ndvi"
    date.fromisoformat(entrada["fecha_imagen"])

    (lat_sur, lon_oeste), (lat_norte, lon_este) = entrada["limites"]
    assert all(es_numero(x) for x in (lat_sur, lon_oeste, lat_norte, lon_este))
    assert lat_sur < lat_norte and lon_oeste < lon_este
    # [lat, lon] y no [lon, lat]: el validador del GeoJSON detecta los invertidos
    for lat, lon in ((lat_sur, lon_oeste), (lat_norte, lon_este)):
        validar_punto(lon, lat, "limites")

    ancho, alto = entrada["ancho"], entrada["alto"]
    assert es_numero(entrada["resolucion_m"]) and entrada["resolucion_m"] > 0
    assert es_entero(ancho) and es_entero(alto)

    valores = entrada["valores"]
    assert isinstance(valores, list) and len(valores) == alto
    for fila in valores:
        assert isinstance(fila, list) and len(fila) == ancho
        assert all(v is None or es_numero(v) for v in fila)

    escala = entrada["escala"]
    assert set(escala) == {"minimo", "maximo", "paleta"}
    assert es_numero(escala["minimo"]) and es_numero(escala["maximo"])
    assert escala["minimo"] < escala["maximo"]
    assert len(escala["paleta"]) >= 2 and all(COLOR.match(c) for c in escala["paleta"])

    # pct_validos es del predio; nubosidad_pct es de toda la escena. No se relacionan entre sí.
    pct_validos, nubosidad = entrada["pct_validos"], entrada["nubosidad_pct"]
    assert es_numero(pct_validos) and 0 <= pct_validos <= 100
    assert nubosidad is None or (es_numero(nubosidad) and 0 <= nubosidad <= 100)
    con_valor = sum(v is not None for fila in valores for v in fila)
    if con_valor == 0:
        assert pct_validos == 0
    else:
        # las celdas con valor son pct_validos % de las del predio, y el predio cabe en la grilla
        assert pct_validos > 0
        assert con_valor * 100 / pct_validos <= ancho * alto * 1.01

    for texto in (entrada["fuente"], entrada["atribucion"], entrada["version_calculo"]):
        assert isinstance(texto, str) and texto
    assert entrada["atribucion"] == (
        f"Contains modified Copernicus Sentinel data {entrada['fecha_imagen'][:4]}"
    )


def debe_fallar(entrada: dict) -> None:
    try:
        validar_entrada(entrada)
    except (AssertionError, AreasMapaError):
        return
    raise AssertionError(f"el validador aceptó una entrada rota: {sorted(entrada)}")


def con_imagen() -> dict:
    return copy.deepcopy(next(e for e in EJEMPLO["mapa_calor"] if "motivo_nulo" not in e))


def sin_imagen() -> dict:
    return copy.deepcopy(next(e for e in EJEMPLO["mapa_calor"] if "motivo_nulo" in e))


# Forma del ejemplo


def test_el_ejemplo_trae_una_entrada_por_estacion_en_el_mismo_orden():
    assert [e["estacion_id"] for e in EJEMPLO["mapa_calor"]] == [
        e["id"] for e in EJEMPLO["estaciones"]
    ]


def test_cada_entrada_del_ejemplo_cumple_la_forma():
    for entrada in EJEMPLO["mapa_calor"]:
        validar_entrada(entrada)


def test_el_ejemplo_cubre_con_y_sin_imagen():
    assert any("motivo_nulo" in e for e in EJEMPLO["mapa_calor"])
    assert any("motivo_nulo" not in e for e in EJEMPLO["mapa_calor"])


def test_la_grilla_del_ejemplo_tiene_celdas_sin_dato_dentro_y_con_dato():
    valores = con_imagen()["valores"]
    planas = [v for fila in valores for v in fila]
    assert any(v is None for v in planas) and any(v is not None for v in planas)


def test_las_estaciones_del_ejemplo_traen_coordenadas_o_null():
    for estacion in EJEMPLO["estaciones"]:
        lat, lon = estacion["latitud"], estacion["longitud"]
        assert lat is None or es_numero(lat)
        assert lon is None or es_numero(lon)
        if lat is not None and lon is not None:
            validar_punto(lon, lat, estacion["id"])
    # el ejemplo muestra los dos casos que tiene que resolver el frontend
    sin_marcador = [
        e for e in EJEMPLO["estaciones"] if e["latitud"] is None or e["longitud"] is None
    ]
    con_marcador = [e for e in EJEMPLO["estaciones"] if e["latitud"] and e["longitud"]]
    assert sin_marcador and con_marcador


def test_el_validador_rechaza_entradas_rotas():
    base = con_imagen()

    debe_fallar({k: v for k, v in base.items() if k != "escala"})
    debe_fallar({**base, "ancho": base["ancho"] + 1})
    debe_fallar({**base, "valores": base["valores"][:-1]})

    (sur, oeste), (norte, este) = base["limites"]
    debe_fallar({**base, "limites": [[oeste, sur], [este, norte]]})  # [lon, lat] por error
    debe_fallar({**base, "limites": [[norte, oeste], [sur, este]]})  # sur al norte del norte

    debe_fallar({**base, "atribucion": "Copernicus"})
    debe_fallar({**base, "pct_validos": 150})
    debe_fallar({**base, "nubosidad_pct": 150})
    debe_fallar({**base, "escala": {**base["escala"], "paleta": ["verde", "rojo"]}})
    debe_fallar({**base, "motivo_nulo": "Sin imagen"})  # con grilla y motivo a la vez
    debe_fallar({**sin_imagen(), "motivo_nulo": ""})


def test_la_nubosidad_de_la_escena_no_depende_del_porcentaje_valido():
    base = con_imagen()
    # una escena casi despejada puede dejar el predio con poco dato, y al revés
    validar_entrada({**base, "nubosidad_pct": 0.0})
    validar_entrada({**base, "nubosidad_pct": 95.0})
    validar_entrada({**base, "nubosidad_pct": None})


# entrada_mapa_calor


def estacion(codigo="cp-prueba-01", longitud=-71.466667):
    return SimpleNamespace(codigo=codigo, longitud=longitud)


def capa(**cambios):
    datos = {
        "capa": "ndvi",
        "fecha_imagen": date(2026, 10, 17),
        "limites_latlon": [-71.4719, -35.5195, -71.4641, -35.5128],  # oeste, sur, este, norte
        "ancho": 3,
        "alto": 2,
        "resolucion_m": 10.0,
        "valores": [[0.41234, None, 0.9], [None, -0.2, 0.55555]],
        "porcentaje_validos": 80.0,
        "nubosidad_pct": 5.5,
        "version": "ndvi-sentinel-2-l2a-v1_scl-cloud-shadow_10m",
    }
    datos.update(cambios)
    return SimpleNamespace(**datos)


def test_entrada_con_imagen_cumple_el_contrato_y_es_json_estricto():
    entrada = entrada_mapa_calor(estacion(), capa())

    validar_entrada(entrada)
    json.dumps(entrada, allow_nan=False)
    assert entrada["estacion_id"] == "cp-prueba-01"
    assert entrada["fecha_imagen"] == "2026-10-17"
    assert entrada["pct_validos"] == 80.0 and entrada["nubosidad_pct"] == 5.5
    assert entrada["version_calculo"] == "ndvi-sentinel-2-l2a-v1_scl-cloud-shadow_10m"
    assert entrada["fuente"] == FUENTE


def test_los_limites_pasan_de_oeste_sur_este_norte_a_lat_lon():
    entrada = entrada_mapa_calor(estacion(), capa())

    assert entrada["limites"] == [[-35.5195, -71.4719], [-35.5128, -71.4641]]


def test_los_valores_se_redondean_y_conservan_nulos_y_orden():
    entrada = entrada_mapa_calor(estacion(), capa())

    assert entrada["valores"] == [[0.412, None, 0.9], [None, -0.2, 0.556]]


def test_la_atribucion_usa_el_anio_de_la_imagen():
    entrada = entrada_mapa_calor(estacion(), capa(fecha_imagen=date(2025, 12, 30)))

    assert entrada["atribucion"] == "Contains modified Copernicus Sentinel data 2025"


def test_cada_entrada_lleva_su_propia_escala():
    primera = entrada_mapa_calor(estacion(), capa())
    primera["escala"]["paleta"].append("#000000")

    assert len(ESCALA["paleta"]) == 7
    assert len(entrada_mapa_calor(estacion(), capa())["escala"]["paleta"]) == 7


def test_sin_imagen_y_con_ubicacion_dice_que_falta_la_imagen():
    entrada = entrada_mapa_calor(estacion(), None)

    validar_entrada(entrada)
    assert entrada["motivo_nulo"] == MOTIVO_SIN_IMAGEN
    assert entrada["estacion_id"] == "cp-prueba-01" and entrada["capa"] == "ndvi"


def test_sin_imagen_y_sin_ubicacion_dice_que_falta_el_predio():
    entrada = entrada_mapa_calor(estacion(longitud=None), None)

    validar_entrada(entrada)
    assert entrada["motivo_nulo"] == MOTIVO_SIN_UBICACION


def test_una_capa_sin_limites_geograficos_no_se_pinta():
    for limites in (None, []):
        entrada = entrada_mapa_calor(estacion(), capa(limites_latlon=limites))

        validar_entrada(entrada)
        assert entrada["motivo_nulo"] == MOTIVO_INCOMPLETA


def test_el_ejemplo_es_lo_que_emite_el_codigo():
    sin_predio = next(e for e in EJEMPLO["mapa_calor"] if "motivo_nulo" in e)
    emitido = entrada_mapa_calor(estacion(sin_predio["estacion_id"], longitud=None), None)
    assert sin_predio == emitido

    con_predio = con_imagen()
    assert set(con_predio) == set(entrada_mapa_calor(estacion(), capa()))
    assert con_predio["escala"] == ESCALA
    assert con_predio["fuente"] == FUENTE
