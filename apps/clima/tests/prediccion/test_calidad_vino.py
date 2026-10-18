import pandas as pd
import pytest

from apps.clima.prediccion.calidad_vino import NIVELES_RECOMMEND, calidad_por_temporada

MEJOR, MEDIO, PEOR = NIVELES_RECOMMEND


def _cosechas():
    return pd.DataFrame(
        {
            "fuente": ["Amerine & Winkler"] * 5 + ["Napa", "Napa"],
            "region": ["I", "I", "I", "I", "II", "II", "II"],
            "anio": [1935, 1935, 1935, 1935, 1935, 2000, 2000],
            "recommend": [MEJOR, MEJOR, MEDIO, PEOR, None, None, None],
            "brix": [22.0, 23.0, 24.0, 25.0, 21.0, 24.0, 26.0],
            "acidez": [0.6, 0.7, 0.8, 0.9, 0.5, None, None],
            "ph": [3.3, 3.4, 3.5, 3.6, 3.2, None, None],
        }
    )


def test_calidad_por_region_anio():
    res = calidad_por_temporada(_cosechas()).set_index(["fuente", "region", "anio"])

    region_i = res.loc[("Amerine & Winkler", "I", 1935)]
    assert region_i["pct_alta"] == 50.0  # 2 de 4 evaluadas
    assert region_i["brix_mediana"] == 23.5
    assert region_i["motivo_nulo"] is None


def test_temporada_sin_evaluaciones_queda_nula_con_motivo():
    res = calidad_por_temporada(_cosechas()).set_index(["fuente", "region", "anio"])

    region_ii = res.loc[("Amerine & Winkler", "II", 1935)]
    assert pd.isna(region_ii["pct_alta"])
    assert region_ii["motivo_nulo"] == "La temporada no tiene evaluaciones."


def test_napa_publica_brix_sin_calidad():
    res = calidad_por_temporada(_cosechas()).set_index(["fuente", "region", "anio"])

    napa = res.loc[("Napa", "II", 2000)]
    assert pd.isna(napa["pct_alta"])
    assert napa["brix_mediana"] == 25.0
    assert "°Brix" in napa["motivo_nulo"]


def test_recommend_desconocido_falla():
    df = _cosechas()
    df.loc[0, "recommend"] = "Inventado"
    with pytest.raises(ValueError, match="Inventado"):
        calidad_por_temporada(df)


@pytest.mark.parametrize("etiqueta", ["Not fully tested", "Table grape"])
def test_etiqueta_sin_clasificacion_no_cuenta_como_baja(etiqueta):
    df = _cosechas()
    df.loc[3, "recommend"] = etiqueta
    df.loc[4, "recommend"] = etiqueta
    res = calidad_por_temporada(df).set_index(["fuente", "region", "anio"])
    assert res.loc[("Amerine & Winkler", "I", 1935), "pct_alta"] == 66.7
    assert pd.isna(res.loc[("Amerine & Winkler", "II", 1935), "pct_alta"])
    assert res.loc[("Amerine & Winkler", "II", 1935), "motivo_nulo"]


def test_escala_usa_las_etiquetas_originales():
    assert NIVELES_RECOMMEND == [
        "Particularly recommended",
        "Limited recommendation",
        "Not recommended",
    ]
