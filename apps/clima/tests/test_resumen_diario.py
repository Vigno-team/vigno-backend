from datetime import date

import pandas as pd
import pytest

from apps.clima.models import ConfiguracionCalidad, Estacion, ResumenDiario
from apps.clima.services import derivar_resumenes_diarios, horas_del_dia
from apps.clima.temporadas import temporada_de

pytestmark = pytest.mark.django_db


def test_temporada_de():
    assert temporada_de(date(2024, 1, 27)) == "2023-2024"
    assert temporada_de(date(2024, 7, 1)) == "2024-2025"


def test_horas_del_dia():
    assert horas_del_dia("2025-09-07") == 23  # Cambio a verano
    assert horas_del_dia("2025-04-05") == 25  # Cambio a invierno
    assert horas_del_dia("2025-07-10") == 24  # Dia normal


def test_horario_manda_sobre_diario():
    estacion = Estacion.objects.create(nombre="Test", codigo="test-01")
    ResumenDiario.objects.create(
        estacion=estacion, fecha=date(2025, 1, 1), temporada="2024-2025", origen="H", tmax=30.0
    )

    # Intentar procesar un dato diario para el mismo día
    df = pd.DataFrame(
        [
            {
                "estacion_id": estacion.id,
                "timestamp": "2025-01-01T12:00:00Z",
                "frecuencia": "D",
                "temperatura_maxima": 25.0,
                "temperatura_minima": 10.0,
                "temperatura_media": 15.0,
                "precipitacion": 0.0,
                "motivo_nulo": None,
            }
        ]
    )
    derivar_resumenes_diarios(df)

    # Verificar que el registro original 'H' no se sobreescribió
    res = ResumenDiario.objects.get(fecha=date(2025, 1, 1))
    assert res.origen == "H"
    assert res.tmax == 30.0


def test_horas_nocturnas_utc_caen_en_dia_correcto():
    estacion = Estacion.objects.create(nombre="Test UTC", codigo="test-02")
    df = pd.DataFrame(
        [
            {
                "estacion_id": estacion.id,
                "timestamp": "2025-07-11T02:00:00Z",  # 22:00 del 10 de julio en Chile
                "frecuencia": "D",
                "temperatura_maxima": 10.0,
            }
        ]
    )
    derivar_resumenes_diarios(df)
    res = ResumenDiario.objects.first()
    assert res.fecha == date(2025, 7, 10)  # Cayó en el 10 de julio


def test_dia_incompleto_no_es_confiable():
    estacion = Estacion.objects.create(nombre="Test Confiable", codigo="test-03")
    ConfiguracionCalidad.obtener_config()  # Crea el config default de 20 hrs

    # Simular solo 2 horas de datos para un día
    df = pd.DataFrame(
        [
            {
                "estacion_id": estacion.id,
                "timestamp": "2025-01-01T12:00:00Z",
                "frecuencia": "H",
                "temperatura_media": 15,
                "temperatura_maxima": 20,
                "temperatura_minima": 10,
            },
            {
                "estacion_id": estacion.id,
                "timestamp": "2025-01-01T13:00:00Z",
                "frecuencia": "H",
                "temperatura_media": 16,
                "temperatura_maxima": 21,
                "temperatura_minima": 11,
            },
        ]
    )
    derivar_resumenes_diarios(df)

    res = ResumenDiario.objects.first()
    assert res.horas_validas == 2
    assert res.confiable is False
