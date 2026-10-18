from datetime import date, timedelta

import pytest

from apps.clima.lluvia_fuera_invierno import _medir
from apps.clima.metricas import version_calculo


@pytest.mark.parametrize(
    "metrica,esperada",
    [
        ("winkler", "winkler-v1_base10_1001-0430"),
        ("huglin", "huglin-v1_base10_1001-0331"),
        ("dias_sobre_umbral", "dias_umbral-v2_36.5c_1001-0430"),
        ("lluvia_invernal", "lluvia-invernal-v1_0105-3108"),
    ],
)
def test_version_publicada_conserva_el_contrato(metrica, esperada, settings):
    settings.UMBRAL_CALOR_C = 36.5
    assert version_calculo(metrica, "2024-2025") == esperada


@pytest.mark.parametrize("cantidad,confiable", [(1999, False), (2000, True)])
def test_lluvia_decide_antes_de_redondear_al_80_por_ciento(cantidad, confiable):
    inicio = date(2000, 1, 1)
    fin = inicio + timedelta(days=2499)
    lluvia = {inicio + timedelta(days=i): 0.0 for i in range(cantidad)}
    resultado = _medir(lluvia, inicio, fin, fin, 80)
    # 1999/2500 = 79,96 %, que se muestra como 80,0 pero no alcanza el umbral.
    assert resultado["completitud_pct"] == 80.0
    assert resultado["confiable"] is confiable
    assert resultado["mm"] == 0.0


def test_lluvia_sin_datos_no_es_confiable_aunque_umbral_sea_cero():
    inicio = date(2024, 10, 1)
    resultado = _medir({}, inicio, inicio, inicio, 0)
    assert resultado["mm"] is None
    assert resultado["confiable"] is False
