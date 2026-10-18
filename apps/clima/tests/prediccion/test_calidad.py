import os

import pandas as pd

from apps.clima.prediccion.calidad import evaluar_calidad, procesar_calidad_temporadas


def test_evaluar_calidad():
    assert evaluar_calidad({"recommend": "Top Tier"}) == "Top Tier"
    assert evaluar_calidad({"brix": 24.5}) == "Excelente"
    assert evaluar_calidad({"brix": 21.0}) == "Buena"
    assert evaluar_calidad({"brix": 18.0}) == "Regular"
    assert evaluar_calidad({"brix": None}) == "Sin datos"


def test_procesamiento_clasificacion(tmp_path):
    df_in = pd.DataFrame(
        {
            "anio": [1990, 1991, 1992],
            "brix": [24.0, 21.0, None],
            "recommend": [None, None, "Premium"],
        }
    )

    ruta_in = tmp_path / "cosechas.csv"
    ruta_out = tmp_path / "cosechas_clasificadas.csv"
    df_in.to_csv(ruta_in, index=False)

    df_res = procesar_calidad_temporadas(ruta_in, ruta_out)

    assert os.path.exists(ruta_out)
    assert list(df_res["calidad_estimada"]) == ["Excelente", "Buena", "Premium"]
