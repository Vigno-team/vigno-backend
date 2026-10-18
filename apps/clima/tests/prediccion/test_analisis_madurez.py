import pandas as pd

from apps.clima.prediccion.analisis_madurez import correlacionar_clima_madurez


def test_winkler_vs_doy_negativo_por_region_anio(tmp_path):
    # 6 temporadas región-año, con 2 cultivares cada una: más calor, cosecha más temprana.
    filas = []
    for i, (wi, doy) in enumerate(
        zip([1000, 1200, 1400, 1600, 1800, 2000], [300, 280, 260, 240, 220, 200], strict=True)
    ):
        for cultivar, desfase in (("Cabernet", 0), ("Merlot", 4)):
            filas.append(
                {
                    "fuente": "Amerine & Winkler",
                    "region": "I" if i < 3 else "II",
                    "anio": 1935 + i,
                    "cultivar": cultivar,
                    "doy": doy + desfase,
                    "brix": 22.0 + i,
                    "wi": wi,
                    "hi": wi + 600,
                    "gst": 14.0 + i,
                }
            )
    ruta = tmp_path / "cosechas.csv"
    pd.DataFrame(filas).to_csv(ruta, index=False)

    resultados = correlacionar_clima_madurez(ruta)

    winkler_doy = next(r for r in resultados if r["indice"] == "winkler" and r["objetivo"] == "doy")
    assert winkler_doy["nivel"] == "region_anio"
    assert winkler_doy["n"] == 6  # una fila por temporada, no 12 registros
    assert winkler_doy["rho"] == -1.0
    assert set(winkler_doy) == {"indice", "objetivo", "nivel", "n", "rho", "p", "p_holm"}
    assert winkler_doy["p"] <= winkler_doy["p_holm"] <= 1
    # Sin acidez ni pH en el CSV, esos objetivos no aparecen.
    assert {r["objetivo"] for r in resultados} == {"doy", "brix"}
