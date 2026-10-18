import pandas as pd

from apps.clima.prediccion.analogos import calcular_analogos


def test_calcular_analogos_identicos():
    # Simular el CSV de temporadas clasificadas
    df_historico = pd.DataFrame(
        {
            "fuente": ["Amerine", "Napa"],
            "region": ["I", "II"],
            "anio": [1990, 1991],
            "wi": [1500, 2000],
            "hi": [2200, 2500],
            "gst": [16.0, 18.0],
            "doy": [240, 250],
            "doy_hs": [240 + 182, 250 + 182],  # 422 y 432
            "calidad_estimada": ["Excelente", "Buena"],
            "brix": [24.0, 21.0],
        }
    )

    # Una temporada en VIGNO que es EXACTAMENTE igual al año 1990
    temp_vigno = {"winkler": 1500, "huglin": 2200, "gst": 16.0}

    # 1. Probar parametrización (conjunto de variables modificable)
    res = calcular_analogos(temp_vigno, df_historico, variables=["winkler", "huglin", "gst"])

    assert len(res) == 2
    mejor = res[0]

    # 2. Una temporada idéntica debe tener similitud máxima (100%)
    assert mejor["temporada_ficticia"] == "Amerine I 1990"
    assert mejor["similitud_pct"] == 100.0

    # 3. Debe devolver fechas, calidades y brix
    assert mejor["calidad"] == "Excelente"
    assert mejor["brix"] == 24.0
    assert "fecha_chile" in mejor

    # 4. Variable explicativa presente
    assert mejor["variable_explicativa"] in ["winkler", "huglin", "gst"]


def test_calcular_analogos_sin_datos():
    res = calcular_analogos({"winkler": 1000}, pd.DataFrame())
    assert res == []
