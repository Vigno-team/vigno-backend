from datetime import date, timedelta

import pytest

from apps.clima.dias_criticos import calcular_dias_sobre_umbral, obtener_dias_criticos
from apps.clima.models import Estacion, IndiceClimatico, ResumenDiario


@pytest.fixture
def estacion_prueba():
    return Estacion.objects.create(nombre="Test Station", latitud=-35.52)


@pytest.mark.django_db
def test_calcular_dias_sobre_umbral(estacion_prueba):
    temporada = "2024-2025"
    # Insertar datos: 2 días sobre 35, 1 día bajo 35
    ResumenDiario.objects.create(
        estacion=estacion_prueba, fecha=date(2025, 1, 1), temporada=temporada, tmax=36.0
    )
    ResumenDiario.objects.create(
        estacion=estacion_prueba, fecha=date(2025, 1, 2), temporada=temporada, tmax=35.0
    )
    ResumenDiario.objects.create(
        estacion=estacion_prueba, fecha=date(2025, 1, 3), temporada=temporada, tmax=34.9
    )

    # Prueba con umbral por defecto (35.0)
    total_dias = calcular_dias_sobre_umbral(estacion_prueba, temporada)
    assert total_dias == 2

    # Validar persistencia en IndiceClimatico
    indice_bd = IndiceClimatico.objects.get(
        estacion=estacion_prueba, indice="DiasSobreUmbral", temporada=temporada
    )
    assert indice_bd.valor == 2.0
    assert indice_bd.parametros["umbral_tmax"] == 35.0
    assert indice_bd.version_calculo == "dias_umbral-v1_35c"
    assert indice_bd.clasificacion is None

    # Prueba recalculando con umbral distinto
    total_dias_ajustado = calcular_dias_sobre_umbral(estacion_prueba, temporada, umbral=36.0)
    assert total_dias_ajustado == 1


@pytest.mark.django_db
def test_temporada_sin_temperaturas_no_guarda_indice(estacion_prueba):
    temporada = "2020-2021"
    for i in range(1, 6):
        ResumenDiario.objects.create(
            estacion=estacion_prueba, fecha=date(2021, 1, i), temporada=temporada, tmax=None
        )

    total_dias = calcular_dias_sobre_umbral(estacion_prueba, temporada)

    assert total_dias == 0
    assert not IndiceClimatico.objects.filter(
        estacion=estacion_prueba, indice="DiasSobreUmbral"
    ).exists()


@pytest.mark.django_db
def test_baja_completitud_no_es_confiable(estacion_prueba):
    temporada = "2024-2025"
    ResumenDiario.objects.create(
        estacion=estacion_prueba, fecha=date(2025, 1, 1), temporada=temporada, tmax=36.0
    )

    calcular_dias_sobre_umbral(estacion_prueba, temporada)

    indice = IndiceClimatico.objects.get(estacion=estacion_prueba, indice="DiasSobreUmbral")
    assert indice.confiable is False
    assert indice.dias_con_dato == 1
    assert indice.dias_esperados == 212  # 1-oct a 30-abr
    assert indice.clasificacion is None


@pytest.mark.django_db
def test_alta_completitud_es_confiable(estacion_prueba):
    temporada = "2024-2025"
    inicio = date(2024, 10, 1)
    # 200 de 212 días (94 %) supera el umbral por defecto de 80 %
    for i in range(200):
        ResumenDiario.objects.create(
            estacion=estacion_prueba,
            fecha=inicio + timedelta(days=i),
            temporada=temporada,
            tmax=30.0,
        )

    total_dias = calcular_dias_sobre_umbral(estacion_prueba, temporada)

    assert total_dias == 0
    indice = IndiceClimatico.objects.get(estacion=estacion_prueba, indice="DiasSobreUmbral")
    assert indice.confiable is True
    assert indice.dias_con_dato == 200


@pytest.mark.django_db
def test_obtener_dias_criticos(estacion_prueba):
    temporada = "2024-2025"
    # Crear 15 registros con distintas temperaturas
    for i in range(1, 16):
        ResumenDiario.objects.create(
            estacion=estacion_prueba,
            fecha=date(2025, 1, i),
            temporada=temporada,
            tmax=20.0 + i,  # tmax de 21.0 a 35.0
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


@pytest.mark.django_db
def test_dia_con_tmax_nulo_no_aparece_en_criticos(estacion_prueba):
    temporada = "2024-2025"
    ResumenDiario.objects.create(
        estacion=estacion_prueba, fecha=date(2025, 1, 1), temporada=temporada, tmax=36.0
    )
    ResumenDiario.objects.create(
        estacion=estacion_prueba, fecha=date(2025, 1, 2), temporada=temporada, tmax=None
    )

    dias_criticos = obtener_dias_criticos(estacion_prueba, temporada)

    assert dias_criticos == [{"fecha": "2025-01-01", "tmax": 36.0}]


@pytest.mark.django_db
@pytest.mark.parametrize("limite", [0, -1])
def test_limite_invalido_lanza_error(estacion_prueba, limite):
    with pytest.raises(ValueError, match="mayor a 0"):
        obtener_dias_criticos(estacion_prueba, "2024-2025", limite=limite)
