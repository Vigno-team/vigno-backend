from datetime import date

import pytest

from apps.clima.indices import (
    calcular_indice_huglin,
    calcular_indice_winkler,
    clasificar_winkler,
    k_huglin,
)
from apps.clima.models import ConfiguracionCalidad, Estacion, IndiceClimatico, ResumenDiario


@pytest.fixture
def estacion_prueba():
    return Estacion.objects.create(nombre="Test Station", latitud=35.5)


@pytest.mark.django_db
def test_winkler_completo_con_resumen_diario(estacion_prueba):
    ConfiguracionCalidad.objects.create(clave="umbral_completitud_pct", umbral_pct=80.0)
    # Rango de 2024-2025 para Winkler es de 1 oct a 30 abr (212 dias)
    # Insertaremos 200 dias de datos validos para que sea confiable
    ini = date(2024, 10, 1)
    # Simular datos para 2 días específicos
    ResumenDiario.objects.create(
        estacion=estacion_prueba, fecha=ini, temporada="2024-2025", tmedia=20.0, tmax=25.0
    )
    ResumenDiario.objects.create(
        estacion=estacion_prueba,
        fecha=date(2024, 10, 2),
        temporada="2024-2025",
        tmedia=10.0,
        tmax=15.0,
    )

    calcular_indice_winkler(estacion_prueba, "2024-2025")

    indice = IndiceClimatico.objects.get(
        estacion=estacion_prueba, indice="Winkler", temporada="2024-2025"
    )
    assert indice.valor == 10.0  # (20 - 10) + max((10 - 10), 0)
    assert indice.dias_con_dato == 2
    assert indice.dias_esperados == 212
    assert indice.confiable is False  # 2/212 = 0.9% < 80%
    assert indice.clasificacion == "Sin datos suficientes"


@pytest.mark.django_db
def test_huglin_con_k_y_tmedia(estacion_prueba):
    ConfiguracionCalidad.objects.create(clave="umbral_completitud_pct", umbral_pct=80.0)
    ini = date(2024, 10, 1)
    # Huglin usa ((Tmedia - 10) + (Tmax - 10))/2 * K
    # Dia 1: Tmedia=20, Tmax=30 -> ((10) + (20))/2 = 15
    ResumenDiario.objects.create(
        estacion=estacion_prueba, fecha=ini, temporada="2024-2025", tmedia=20.0, tmax=30.0
    )

    calcular_indice_huglin(estacion_prueba, "2024-2025")

    indice = IndiceClimatico.objects.get(
        estacion=estacion_prueba, indice="Huglin", temporada="2024-2025"
    )
    assert indice.valor == 15.0
    assert indice.parametros["k"] == 1.00  # latitud 35.5 -> k=1.00


@pytest.mark.django_db
def test_k_huglin_por_latitud():
    assert k_huglin(35.0) == 1.00
    assert k_huglin(41.0) == 1.02
    assert k_huglin(-47.0) == 1.05


def test_clasificar_winkler():
    assert clasificar_winkler(1389) == "Región I"
    assert clasificar_winkler(1390) == "Región II"
    assert clasificar_winkler(2223) == "Región V"


@pytest.mark.django_db
def test_huglin_sin_latitud_no_es_confiable():
    est = Estacion.objects.create(nombre="Sin Latitud", latitud=None)
    ConfiguracionCalidad.objects.create(
        clave="umbral_completitud_pct", umbral_pct=0.0
    )  # 0% to ensure completeness doesn't fail
    ini = date(2024, 10, 1)
    ResumenDiario.objects.create(
        estacion=est, fecha=ini, temporada="2024-2025", tmedia=20.0, tmax=30.0
    )

    calcular_indice_huglin(est, "2024-2025")

    indice = IndiceClimatico.objects.get(estacion=est, indice="Huglin", temporada="2024-2025")
    assert indice.confiable is False
    assert indice.parametros["latitud"] is None
