import pandas as pd

from apps.clima.prediccion.correlaciones import calcular_spearman_holm


def test_correlacion_winkler_doy_negativa():
    # Simula el criterio de la H39: Mayor calor -> cosecha más temprana
    df = pd.DataFrame(
        {"wi": [1000, 1200, 1400, 1600, 1800, 2000], "doy": [300, 280, 260, 240, 220, 200]}
    )
    rho, p, n = calcular_spearman_holm(df, "wi", "doy")
    assert rho < 0
    assert rho == -1.0
    assert n == 6
