from datetime import date, timedelta

import pytest

from apps.clima.models import Estacion, ResumenDiario
from apps.clima.rachas import identificar_rachas


@pytest.fixture
def estacion_prueba():
    return Estacion.objects.create(nombre="Estacion Rachas", latitud=-35.0)


def crear_dias(estacion, temperaturas, fecha_inicial=None):
    if fecha_inicial is None:
        fecha_inicial = date(2023, 7, 1)  # Inicio de temporada 2023-2024

    for i, tmax in enumerate(temperaturas):
        ResumenDiario.objects.create(
            estacion=estacion,
            fecha=fecha_inicial + timedelta(days=i),
            temporada="2023-2024",
            tmax=tmax,
        )


@pytest.mark.django_db
def test_identificar_rachas_detecta_secuencia(estacion_prueba):
    crear_dias(estacion_prueba, [30.0, 36.0, 37.0, 34.0])
    rachas = identificar_rachas(estacion_prueba, "2023-2024", umbral_temp=35.0)

    assert len(rachas) == 1
    assert rachas[0]["dias"] == 2
    assert rachas[0]["inicio"] == date(2023, 7, 2)
    assert rachas[0]["fin"] == date(2023, 7, 3)
    assert rachas[0]["tmax_maxima"] == 37.0
    assert rachas[0]["con_incidencia"] is False
    assert rachas[0]["interrumpida_por_dato_faltante"] is False


@pytest.mark.django_db
def test_identificar_rachas_incidencia(estacion_prueba):
    temps = [36.0] * 4 + [30.0] + [36.0] * 5
    crear_dias(estacion_prueba, temps)

    rachas = identificar_rachas(estacion_prueba, "2023-2024", umbral_temp=35.0, min_dias=5)

    assert len(rachas) == 2
    assert rachas[0]["dias"] == 4
    assert rachas[0]["con_incidencia"] is False

    assert rachas[1]["dias"] == 5
    assert rachas[1]["con_incidencia"] is True


@pytest.mark.django_db
def test_identificar_rachas_umbral_parametrizable(estacion_prueba):
    temps = [33.0, 34.0, 35.0, 34.0, 32.0]
    crear_dias(estacion_prueba, temps)

    rachas_35 = identificar_rachas(estacion_prueba, "2023-2024", umbral_temp=35.0)
    assert len(rachas_35) == 1
    assert rachas_35[0]["dias"] == 1
    assert rachas_35[0]["tmax_maxima"] == 35.0

    rachas_33 = identificar_rachas(estacion_prueba, "2023-2024", umbral_temp=33.0)
    assert len(rachas_33) == 1
    assert rachas_33[0]["dias"] == 4
    assert rachas_33[0]["tmax_maxima"] == 35.0


@pytest.mark.django_db
def test_identificar_rachas_hueco_antes(estacion_prueba):
    # Dia 1 existe (pero fecha > inicio_temp) -> Gap before
    # [vacio antes]
    ResumenDiario.objects.create(
        estacion=estacion_prueba, fecha=date(2023, 8, 1), temporada="2023-2024", tmax=36.0
    )

    rachas = identificar_rachas(estacion_prueba, "2023-2024")
    assert len(rachas) == 1
    assert rachas[0]["interrumpida_por_dato_faltante"] is True


@pytest.mark.django_db
def test_identificar_rachas_nulo_antes(estacion_prueba):
    # Dia 1 nulo, Dia 2 36.0 -> Racha interrumpida antes
    ResumenDiario.objects.create(
        estacion=estacion_prueba, fecha=date(2023, 7, 1), temporada="2023-2024", tmax=None
    )
    ResumenDiario.objects.create(
        estacion=estacion_prueba, fecha=date(2023, 7, 2), temporada="2023-2024", tmax=36.0
    )

    rachas = identificar_rachas(estacion_prueba, "2023-2024")
    assert len(rachas) == 1
    assert rachas[0]["interrumpida_por_dato_faltante"] is True


@pytest.mark.django_db
def test_identificar_rachas_termino_antes_de_junio(estacion_prueba):
    # La temporada 2023-2024 termina en junio 2024
    ResumenDiario.objects.create(
        estacion=estacion_prueba, fecha=date(2023, 7, 1), temporada="2023-2024", tmax=36.0
    )
    # Faltan datos el resto del ao
    rachas = identificar_rachas(estacion_prueba, "2023-2024")
    assert len(rachas) == 1
    assert rachas[0]["interrumpida_por_dato_faltante"] is True


@pytest.mark.django_db
def test_identificar_rachas_malos_inputs(estacion_prueba):
    crear_dias(estacion_prueba, [36.0, 36.0, 36.0])

    with pytest.raises(ValueError, match="num"):
        identificar_rachas(estacion_prueba, "2023-2024", umbral_temp="basura")

    with pytest.raises(ValueError, match="mayor a 0"):
        identificar_rachas(estacion_prueba, "2023-2024", min_dias=0)
