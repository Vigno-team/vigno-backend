from datetime import date

import pytest

from apps.clima.lluvia_fuera_invierno import _fecha_en_anio
from apps.clima.temporadas import (
    rango_crecimiento,
    rango_dias_calor,
    rango_huglin,
    rango_invernal,
    rango_temporada,
    rango_winkler,
    rangos_etapas_crecimiento,
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


def test_etapas_contiguas_y_sin_huecos():
    etapas = list(rangos_etapas_crecimiento("2024-2025").values())
    assert etapas[0][0] == rango_crecimiento("2024-2025")[0]
    assert etapas[-1][1] == rango_crecimiento("2024-2025")[1]
    for (_, fin), (inicio_siguiente, _) in zip(etapas, etapas[1:], strict=False):
        assert inicio_siguiente == date.fromordinal(fin.toordinal() + 1)


def test_rango_crecimiento_se_deriva_de_las_etapas(monkeypatch):
    monkeypatch.setattr(
        "apps.clima.temporadas.ETAPAS_CRECIMIENTO",
        (
            ("brotacion_floracion", (10, 1), (11, 30)),
            ("cuaja_envero", (12, 1), (1, 31)),
            ("maduracion_cosecha", (2, 1), (3, 31)),
        ),
    )

    assert rango_crecimiento("2024-2025") == (date(2024, 10, 1), date(2025, 3, 31))


def test_fecha_de_corte_29_febrero_se_ajusta_en_anio_no_bisiesto():
    assert _fecha_en_anio(date(2024, 2, 29), 2023) == date(2023, 2, 28)
