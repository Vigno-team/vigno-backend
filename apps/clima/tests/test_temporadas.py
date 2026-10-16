from datetime import date

import pytest

from apps.clima.temporadas import (
    rango_dias_calor,
    rango_huglin,
    rango_invernal,
    rango_temporada,
    rango_winkler,
)


@pytest.mark.parametrize(
    ("funcion", "esperado"),
    [
        (rango_temporada, (date(2024, 7, 1), date(2025, 6, 30))),
        (rango_invernal, (date(2024, 5, 1), date(2024, 8, 31))),
        (rango_winkler, (date(2024, 10, 1), date(2025, 4, 30))),
        (rango_huglin, (date(2024, 10, 1), date(2025, 3, 31))),
        (rango_dias_calor, (date(2024, 10, 1), date(2025, 4, 30))),
    ],
)
def test_ventanas_de_la_temporada_2024_2025(funcion, esperado):
    assert funcion("2024-2025") == esperado


def test_winkler_es_mas_largo_que_huglin():
    assert rango_winkler("2023-2024")[1] > rango_huglin("2023-2024")[1]
