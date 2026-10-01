from datetime import UTC, datetime

import pytest

from apps.clima.indices import calcular_indice_huglin, calcular_indice_winkler
from apps.clima.models import Estacion, IndiceClimatico, MedicionHoraria


@pytest.fixture
def estacion_prueba():
    est = Estacion.objects.create(nombre="Test Station")
    # Dia 1: max=30, min=10 -> media=20
    dt1 = datetime(2024, 1, 1, 12, 0, tzinfo=UTC)
    MedicionHoraria.objects.create(estacion=est, timestamp=dt1, variable="temperatura_maxima", valor=30.0, frecuencia="D")
    MedicionHoraria.objects.create(estacion=est, timestamp=dt1, variable="temperatura_minima", valor=10.0, frecuencia="D")
    
    # Dia 2: max=15, min=5 -> media=10
    dt2 = datetime(2024, 1, 2, 12, 0, tzinfo=UTC)
    MedicionHoraria.objects.create(estacion=est, timestamp=dt2, variable="temperatura_maxima", valor=15.0, frecuencia="D")
    MedicionHoraria.objects.create(estacion=est, timestamp=dt2, variable="temperatura_minima", valor=5.0, frecuencia="D")
    return est

@pytest.mark.django_db
def test_calcular_indice_winkler(estacion_prueba):
    # Winkler = (20 - 10) + max((10 - 10), 0) = 10
    resultado = calcular_indice_winkler("Test Station", "2024-01-01", "2024-01-02", temporada="2023-2024")
    assert resultado == 10.0
    
    # Validar registro en base de datos con parametros
    indice_bd = IndiceClimatico.objects.get(estacion=estacion_prueba, indice="Winkler", temporada="2023-2024")
    assert indice_bd.valor == 10.0
    assert indice_bd.parametros["temp_base"] == 10.0

@pytest.mark.django_db
def test_calcular_indice_huglin_con_k(estacion_prueba):
    # Huglin dia 1: max(0, ((20-10) + (30-10))/2 ) = max(0, (10+20)/2) = 15
    # Huglin dia 2: max(0, ((10-10) + (15-10))/2 ) = max(0, (0+5)/2) = 2.5
    # Total = 17.5. Con k=1.0 -> 17.5
    resultado = calcular_indice_huglin("Test Station", "2024-01-01", "2024-01-02", temporada="2023-2024", k=1.0)
    assert resultado == 17.5
    
    # Validar registro en base de datos con parametros (verificar actualizacion de parametros)
    indice_bd = IndiceClimatico.objects.get(estacion=estacion_prueba, indice="Huglin", temporada="2023-2024")
    assert indice_bd.parametros["k"] == 1.0

@pytest.mark.django_db
def test_winkler_sin_datos_retorna_cero():
    Estacion.objects.create(nombre="Vacia")
    resultado = calcular_indice_winkler("Vacia", "2024-01-01", "2024-01-03")
    assert resultado == 0.0
