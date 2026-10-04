from datetime import date

import pytest

from apps.clima.dias_criticos import calcular_dias_sobre_umbral, obtener_dias_criticos
from apps.clima.models import Estacion, IndiceClimatico, ResumenDiario


@pytest.fixture
def estacion_prueba():
    return Estacion.objects.create(nombre="Test Station", latitud=35.5)

@pytest.mark.django_db
def test_calcular_dias_sobre_umbral(estacion_prueba):
    temporada = "2024-2025"
    # Insertar datos: 2 días sobre 35, 1 día bajo 35
    ResumenDiario.objects.create(estacion=estacion_prueba, fecha=date(2025, 1, 1), temporada=temporada, tmax=36.0)
    ResumenDiario.objects.create(estacion=estacion_prueba, fecha=date(2025, 1, 2), temporada=temporada, tmax=35.0)
    ResumenDiario.objects.create(estacion=estacion_prueba, fecha=date(2025, 1, 3), temporada=temporada, tmax=34.9)

    # Prueba con umbral por defecto (35.0)
    total_dias = calcular_dias_sobre_umbral(estacion_prueba, temporada)
    assert total_dias == 2
    
    # Validar persistencia en IndiceClimatico
    indice_bd = IndiceClimatico.objects.get(estacion=estacion_prueba, indice="DiasSobreUmbral", temporada=temporada)
    assert indice_bd.valor == 2.0
    assert indice_bd.parametros["umbral_tmax"] == 35.0

    # Prueba recalculando con umbral distinto
    total_dias_ajustado = calcular_dias_sobre_umbral(estacion_prueba, temporada, umbral=36.0)
    assert total_dias_ajustado == 1

@pytest.mark.django_db
def test_obtener_dias_criticos(estacion_prueba):
    temporada = "2024-2025"
    # Crear 15 registros con distintas temperaturas
    for i in range(1, 16):
        ResumenDiario.objects.create(
            estacion=estacion_prueba, 
            fecha=date(2025, 1, i), 
            temporada=temporada, 
            tmax=20.0 + i  # tmax de 21.0 a 35.0
        )
    
    # Probar el límite por defecto (10) y el orden descendente
    dias_criticos = obtener_dias_criticos(estacion_prueba, temporada)
    
    assert len(dias_criticos) == 10
    assert dias_criticos[0]["tmax"] == 35.0  
    assert dias_criticos[-1]["tmax"] == 26.0 
    assert "fecha" in dias_criticos[0]

    # Probar límite parametrizable
    dias_criticos_top_3 = obtener_dias_criticos(estacion_prueba, temporada, limite=3)
    assert len(dias_criticos_top_3) == 3
    assert dias_criticos_top_3[0]["tmax"] == 35.0
    assert dias_criticos_top_3[2]["tmax"] == 33.0