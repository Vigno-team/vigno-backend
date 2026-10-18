"""Tests traídos de archivo/e1c-20 (test_correlaciones_cosecha.py), solo los de correlacion."""

import pytest

from apps.clima.prediccion.correlaciones import _holm, correlacion


@pytest.mark.parametrize(
    "x,y,rho,p",
    [
        ([1, 2, 3], [3, 2, 1], -1, 1 / 3),
        ([1, 2, 3, 4, 5], [1, 2, 3, 4, 5], 1, 1 / 60),
        ([1, 1, 2], [1, 1, 2], 1, 1 / 3),
        ([1, 2, 3], [1, 3, 2], 0.5, 1),
    ],
)
def test_coeficientes_y_p_exactos_conocidos(x, y, rho, p):
    resultado = correlacion(x, y)
    assert resultado["rho"] == pytest.approx(rho)
    assert resultado["p_valor"] == pytest.approx(p)
    assert resultado["prueba"] == "permutacion_exacta"


def test_spearman_con_empates_referencia_scipy():
    # Ejemplo oficial scipy.stats.spearmanr 1.14.1: rho=0.7.
    resultado = correlacion(
        [7.1, 7.1, 7.2, 8.3, 9.4, 10.5, 11.4], [2.8, 2.9, 2.8, 2.6, 3.5, 4.6, 5]
    )
    assert resultado["rho"] == pytest.approx(0.7)
    assert resultado["permutaciones"] == 5040


@pytest.mark.parametrize(
    "x,y,estado",
    [
        ([], [], "muestra_insuficiente"),
        ([1, 2], [2, 1], "muestra_insuficiente"),
        ([1, 1, 1], [2, 3, 4], "serie_constante"),
        ([1, 2, 3], [4, 4, 4], "serie_constante"),
    ],
)
def test_no_inventa_correlaciones(x, y, estado):
    resultado = correlacion(x, y)
    assert resultado["estado"] == estado
    assert resultado["rho"] is None and resultado["p_valor"] is None


@pytest.mark.parametrize(
    "x,y", [([1], []), ([float("nan")] * 3, [1] * 3), ([True] * 3, [1] * 3), ([None] * 3, [1] * 3)]
)
def test_rechaza_series_invalidas(x, y):
    with pytest.raises(ValueError):
        correlacion(x, y)


def test_permutacion_aleatoria_reproducible_y_p_no_cero():
    x = list(range(9))
    a = correlacion(x, x)
    b = correlacion(x, x)
    assert a == b
    assert a["prueba"] == "permutacion_monte_carlo"
    assert a["permutaciones"] == 9999 and 0 < a["p_valor"] <= 1


def test_holm_ordena_y_es_monotono():
    filas = [{"p_valor": 0.04}, {"p_valor": 0.01}, {"p_valor": 0.03}]
    _holm(filas)
    assert [f["p_ajustado_holm"] for f in filas] == pytest.approx([0.06, 0.03, 0.06])
