"""E1C-120: valores independientes y fronteras del motor compartido."""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.clima.metricas import aporte_huglin, aporte_winkler, calidad_metrica, valor_metrica
from apps.clima.models import Estacion, IndiceClimatico, ResumenDiario
from apps.clima.temporadas import temporada_de


@pytest.mark.parametrize(
    "media,maxima,minima,winkler,huglin",
    [
        (20, 30, 10, 10, 15),
        (None, 30, 10, 10, 15),
        (0, 30, 10, 0, 5),
        (5, 8, 2, 0, 0),
        (None, 30, None, None, None),
        (20, None, 10, 10, None),
    ],
)
def test_aportes_diarios_conservan_fallback_ceros_y_nulos(media, maxima, minima, winkler, huglin):
    dia = SimpleNamespace(tmedia=media, tmax=maxima, tmin=minima)
    assert aporte_winkler(dia) == winkler
    assert aporte_huglin(dia, 1) == huglin


@pytest.mark.parametrize(
    "n,esperados,umbral,porcentaje,confiable",
    [
        (0, 0, 0, None, False),
        (0, 212, 0, 0, False),
        (80, 100, 80, 80, True),
        (7996, 10000, 80, 79.96, False),
        (101, 100, 80, 100, True),
    ],
)
def test_calidad_no_promueve_ausencias_ni_redondea_antes_del_umbral(
    n, esperados, umbral, porcentaje, confiable
):
    calidad = calidad_metrica(n, esperados, umbral)
    assert calidad["completitud_pct"] == porcentaje
    assert calidad["confiable"] is confiable


@pytest.fixture
def estacion(db):
    return Estacion.objects.create(nombre="Motor métricas", codigo="motor-metricas", latitud=-41)


def dia(estacion, fecha, **valores):
    return ResumenDiario.objects.create(
        estacion=estacion, fecha=fecha, temporada=temporada_de(fecha), **valores
    )


def test_dias_calor_usa_una_ventana_inclusiva_y_el_setting(estacion, settings):
    settings.UMBRAL_CALOR_C = 36
    for fecha, temperatura in [
        (date(2024, 9, 30), 45),
        (date(2024, 10, 1), 36),
        (date(2025, 1, 1), 35.9),
        (date(2025, 4, 30), 37),
        (date(2025, 5, 1), 45),
    ]:
        dia(estacion, fecha, tmax=temperatura)
    resultado = valor_metrica(estacion, "dias_sobre_umbral", "2024-2025")
    assert resultado["valor"] == 2
    assert resultado["dias_con_dato"] == 3
    assert resultado["dias_esperados"] == 212
    guardable = valor_metrica(estacion, "dias_sobre_umbral", "2024-2025", para_guardar=True)
    assert guardable["parametros"]["umbral_tmax"] == 36
    assert guardable["version_calculo"] == "dias_umbral-v2_36c_1001-0430"


def test_lluvia_invernal_usa_fechas_mayo_agosto_no_etiqueta_de_temporada(estacion):
    for fecha, mm in [
        (date(2024, 4, 30), 99),
        (date(2024, 5, 1), 10),
        (date(2024, 6, 1), 0),
        (date(2024, 8, 31), 20),
        (date(2024, 9, 1), 99),
    ]:
        dia(estacion, fecha, precipitacion=mm)
    resultado = valor_metrica(estacion, "lluvia_invernal", "2024-2025")
    assert resultado["valor"] == 30
    assert resultado["dias_con_dato"] == 3
    assert resultado["dias_esperados"] == 123


@pytest.mark.parametrize("metrica", ["winkler", "huglin", "dias_sobre_umbral", "lluvia_invernal"])
def test_futuro_sin_datos_no_es_cero_ni_confiable(estacion, metrica):
    resultado = valor_metrica(estacion, metrica, "2024-2025", date(2024, 1, 1), 0)
    assert resultado["valor"] is None
    assert resultado["dias_esperados"] == 0
    assert resultado["completitud_pct"] is None
    assert resultado["confiable"] is False


def test_corte_excluye_datos_posteriores_y_cuenta_ceros(estacion):
    dia(estacion, date(2024, 5, 1), precipitacion=0)
    dia(estacion, date(2024, 5, 2), precipitacion=50)
    resultado = valor_metrica(estacion, "lluvia_invernal", "2024-2025", date(2024, 5, 1))
    assert resultado["valor"] == 0
    assert resultado["dias_con_dato"] == resultado["dias_esperados"] == 1
    assert resultado["confiable"] is True


def test_huglin_sin_latitud_nunca_es_confiable(estacion):
    estacion.latitud = None
    dia(estacion, date(2024, 10, 1), tmedia=20, tmax=30)
    resultado = valor_metrica(estacion, "huglin", "2024-2025", date(2024, 10, 1), 0)
    assert resultado["valor"] == 15
    assert resultado["confiable"] is False


def test_ventana_winkler_cuenta_dia_bisiesto(estacion):
    dia(estacion, date(2024, 2, 29), tmedia=20)
    resultado = valor_metrica(estacion, "winkler", "2023-2024")
    assert resultado["valor"] == 10
    assert resultado["dias_esperados"] == 213


def test_motor_sin_escrituras_incluso_para_guardar(estacion):
    dia(estacion, date(2024, 10, 1), tmedia=20)
    with CaptureQueriesContext(connection) as queries:
        resultado = valor_metrica(estacion, "winkler", "2024-2025", para_guardar=True)
    assert resultado["valor"] == 10
    assert not IndiceClimatico.objects.exists()
    assert not any(
        q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries
    )


def test_aisla_estaciones_y_mide_dias_validos_no_filas(estacion):
    otra = Estacion.objects.create(nombre="Otra", codigo="otra")
    for i, valor in enumerate([None, 5, 20]):
        dia(estacion, date(2024, 10, 1) + timedelta(days=i), tmedia=valor)
    dia(otra, date(2024, 10, 1), tmedia=100)
    resultado = valor_metrica(estacion, "winkler", "2024-2025")
    assert resultado["valor"] == 10
    assert resultado["dias_con_dato"] == 2
