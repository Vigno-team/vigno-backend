from datetime import date, timedelta

import pytest

from apps.clima.models import Estacion, ResumenDiario
from apps.clima.rachas import identificar_rachas


@pytest.fixture
def estacion_prueba():
    return Estacion.objects.create(nombre="Estacion Rachas", latitud=-35.0)


def crear_dias(estacion, temperaturas):
    fecha_inicial = date(2024, 1, 1)
    for i, tmax in enumerate(temperaturas):
        ResumenDiario.objects.create(
            estacion=estacion,
            fecha=fecha_inicial + timedelta(days=i),
            temporada="2023-2024",
            tmax=tmax,
        )


@pytest.mark.django_db
def test_identificar_rachas_detecta_secuencia(estacion_prueba):
    # Temperaturas: 30, 36, 37, 34 -> Racha de 2 dias (36 y 37)
    crear_dias(estacion_prueba, [30.0, 36.0, 37.0, 34.0])
    rachas = identificar_rachas(estacion_prueba, "2023-2024", umbral_temp=35.0)

    assert len(rachas) == 1
    assert rachas[0]["duracion"] == 2
    assert rachas[0]["inicio"] == date(2024, 1, 2)
    assert rachas[0]["fin"] == date(2024, 1, 3)
    assert rachas[0]["incidencia"] is False
    assert rachas[0]["interrumpida_por_dato_faltante"] is False


@pytest.mark.django_db
def test_identificar_rachas_incidencia(estacion_prueba):
    # 4 dias sobre 35, 1 bajo 35, 5 dias sobre 35
    temps = [36.0] * 4 + [30.0] + [36.0] * 5
    crear_dias(estacion_prueba, temps)

    rachas = identificar_rachas(estacion_prueba, "2023-2024", umbral_temp=35.0, min_dias=5)

    assert len(rachas) == 2
    assert rachas[0]["duracion"] == 4
    assert rachas[0]["incidencia"] is False

    assert rachas[1]["duracion"] == 5
    assert rachas[1]["incidencia"] is True


@pytest.mark.django_db
def test_identificar_rachas_umbral_parametrizable(estacion_prueba):
    temps = [33.0, 34.0, 35.0, 34.0, 32.0]
    crear_dias(estacion_prueba, temps)

    # Con umbral 35 (>= 35)
    rachas_35 = identificar_rachas(estacion_prueba, "2023-2024", umbral_temp=35.0)
    assert len(rachas_35) == 1
    assert rachas_35[0]["duracion"] == 1

    # Con umbral 33 (>= 33)
    rachas_33 = identificar_rachas(estacion_prueba, "2023-2024", umbral_temp=33.0)
    assert len(rachas_33) == 1
    assert rachas_33[0]["duracion"] == 4


@pytest.mark.django_db
def test_identificar_rachas_huecos_en_bd(estacion_prueba):
    # Falta el dia 2 intencionalmente
    ResumenDiario.objects.create(
        estacion=estacion_prueba, fecha=date(2024, 1, 1), temporada="2023-2024", tmax=36.0
    )
    ResumenDiario.objects.create(
        estacion=estacion_prueba, fecha=date(2024, 1, 3), temporada="2023-2024", tmax=36.0
    )

    rachas = identificar_rachas(estacion_prueba, "2023-2024")
    assert len(rachas) == 2
    assert rachas[0]["duracion"] == 1
    assert rachas[0]["interrumpida_por_dato_faltante"] is True
    assert rachas[1]["duracion"] == 1


@pytest.mark.django_db
def test_identificar_rachas_dato_nulo(estacion_prueba):
    # Dia 2 tiene tmax = None
    ResumenDiario.objects.create(
        estacion=estacion_prueba, fecha=date(2024, 1, 1), temporada="2023-2024", tmax=36.0
    )
    ResumenDiario.objects.create(
        estacion=estacion_prueba, fecha=date(2024, 1, 2), temporada="2023-2024", tmax=None
    )
    ResumenDiario.objects.create(
        estacion=estacion_prueba, fecha=date(2024, 1, 3), temporada="2023-2024", tmax=36.0
    )

    rachas = identificar_rachas(estacion_prueba, "2023-2024")
    assert len(rachas) == 2
    assert rachas[0]["duracion"] == 1
    assert rachas[0]["interrumpida_por_dato_faltante"] is True
    assert rachas[1]["duracion"] == 1


@pytest.mark.django_db
def test_identificar_rachas_dataset_vacio(estacion_prueba):
    rachas = identificar_rachas(estacion_prueba, "1990-1991")
    assert rachas == []


@pytest.mark.django_db
def test_identificar_rachas_malos_inputs(estacion_prueba):
    crear_dias(estacion_prueba, [36.0, 36.0, 36.0])
    rachas = identificar_rachas(estacion_prueba, "2023-2024", umbral_temp="35.0", min_dias="2")
    assert len(rachas) == 1
    assert rachas[0]["duracion"] == 3
    assert rachas[0]["incidencia"] is True

    rachas_basura = identificar_rachas(
        estacion_prueba, "2023-2024", umbral_temp="basura", min_dias="texto"
    )
    assert len(rachas_basura) == 1
    assert rachas_basura[0]["duracion"] == 3
    assert rachas_basura[0]["incidencia"] is False
