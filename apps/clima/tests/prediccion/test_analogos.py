import pandas as pd
import pytest

from apps.clima.models import Estacion, IndiceClimatico
from apps.clima.prediccion.analogos import calcular_analogos, obtener_analogos_vigno


def _historico():
    # Cosechas del CSV de E1C-78: 2 registros por temporada en la región I.
    return pd.DataFrame(
        {
            "fuente": ["Amerine & Winkler"] * 4 + ["Napa"],
            "region": ["I", "I", "III", "III", "II"],
            "anio": [1935, 1935, 1936, 1936, 2004],
            "wi": [1500, 1500, 2000, 2000, 1700],
            "hi": [2200, 2200, 2500, 2500, 2300],
            "gst": [16.0, 16.0, 18.0, 18.0, 17.0],
            "doy": [238, 242, 250, 250, 245],
            "doy_hs": [420, 424, 432, 432, 427],
            "brix": [23.0, 25.0, 21.0, 21.0, 24.6],
        }
    )


def _calidad():
    # Salida de calidad_por_temporada (E1C-79).
    return pd.DataFrame(
        {
            "fuente": ["Amerine & Winkler", "Amerine & Winkler", "Napa"],
            "region": ["I", "III", "II"],
            "anio": [1935, 1936, 2004],
            "pct_alta": [75.0, 20.0, None],
            "motivo_nulo": [None, None, "Napa solo trae °Brix; no tiene evaluación de calidad."],
        }
    )


def test_temporada_identica_tiene_similitud_maxima():
    vigno = {"winkler": 1500, "huglin": 2200, "gst": 16.0}

    res = calcular_analogos(
        vigno, _historico(), 2024, variables=["winkler", "huglin", "gst"], calidad=_calidad()
    )

    assert len(res) == 3
    assert res[0] == {
        "origen": "Región I 1935",
        "similitud_pct": 100.0,
        "doy": 240.0,
        "fecha_equivalente": "2025-02-25",  # 1-ene-2024 + 422 - 1 días
        "calidad": {"pct_alta": 75.0, "motivo_nulo": None},
        "brix": 24.0,
        "explica": "winkler",
    }
    assert res[1]["origen"] == "Napa 2004"
    assert res[1]["calidad"]["motivo_nulo"].startswith("Napa solo trae")
    assert res[0]["similitud_pct"] > res[1]["similitud_pct"] > res[2]["similitud_pct"]


def test_las_variables_son_un_parametro():
    # Por Winkler se parece a Napa 2004; por Huglin, a la región III de 1936.
    vigno = {"winkler": 1700, "huglin": 2500}

    solo_winkler = calcular_analogos(vigno, _historico(), 2024, variables=["winkler"])
    solo_huglin = calcular_analogos(vigno, _historico(), 2024, variables=["huglin"])

    assert solo_winkler[0]["origen"] == "Napa 2004"
    assert solo_huglin[0]["origen"] == "Región III 1936"
    assert solo_winkler[0]["calidad"] == {"pct_alta": None, "motivo_nulo": None}


def test_sin_historico_devuelve_lista_vacia():
    assert calcular_analogos({"winkler": 1000, "huglin": 2000}, pd.DataFrame(), 2024) == []


def test_falta_una_variable_de_la_temporada():
    with pytest.raises(ValueError, match="huglin"):
        calcular_analogos({"winkler": 1000}, _historico(), 2024)


@pytest.mark.django_db
def test_lee_winkler_y_huglin_confiables_de_indice_climatico():
    arenal = Estacion.objects.get(nombre="El Arenal")
    otra = Estacion.objects.create(nombre="Otra", codigo="otra-01")
    for estacion, temporada, indice, valor, confiable in [
        (arenal, "2024-2025", "Winkler", 1500, True),
        (arenal, "2024-2025", "Huglin", 2200, True),
        (arenal, "2023-2024", "Winkler", 1600, True),
        (arenal, "2023-2024", "Huglin", 2300, False),  # no confiable: se omite la temporada
        (otra, "2024-2025", "Winkler", 1500, True),
        (otra, "2024-2025", "Huglin", 2200, True),
    ]:
        IndiceClimatico.objects.create(
            estacion=estacion, temporada=temporada, indice=indice, valor=valor, confiable=confiable
        )

    res = obtener_analogos_vigno(_historico(), calidad=_calidad())

    assert [(r["estacion_id"], r["temporada"]) for r in res] == [(arenal.codigo, "2024-2025")]
    assert res[0]["indices"] == {"wi": 1500, "hi": 2200}
    assert res[0]["anios_analogos"][0]["origen"] == "Región I 1935"
