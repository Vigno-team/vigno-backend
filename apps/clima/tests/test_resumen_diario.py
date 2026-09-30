import json
from datetime import date

import pandas as pd
import pytest
from django.conf import settings
from django.core.management import call_command

from apps.clima.models import ConfiguracionCalidad, Estacion, MedicionHoraria, ResumenDiario
from apps.clima.services import (
    completitud_por_temporada,
    derivar_resumenes_diarios,
    estaciones,
    horas_del_dia,
    resumen_diario,
    temporadas,
)
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

    # Intentar procesar un dato diario para el mismo dia
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
                "frecuencia": "H",
                "temperatura_media": 10.0,
            }
        ]
    )
    derivar_resumenes_diarios(df)
    res = ResumenDiario.objects.get()
    assert res.fecha == date(2025, 7, 10)


def test_dia_incompleto_no_es_confiable():
    estacion = Estacion.objects.create(nombre="Test Confiable", codigo="test-03")
    ConfiguracionCalidad.obtener_config()

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


def test_pivot_no_inventa_dias_entre_estaciones():
    a = Estacion.objects.create(nombre="A", codigo="a")
    b = Estacion.objects.create(nombre="B", codigo="b")
    for est, ts in [(a, "2021-01-01T12:00:00Z"), (b, "2020-01-01T12:00:00Z")]:
        for var, val in [("temperatura_maxima", 25.0), ("temperatura_minima", 10.0)]:
            MedicionHoraria.objects.create(
                estacion=est, timestamp=ts, variable=var, frecuencia="D", valor=val
            )
    call_command("generar_resumenes")

    assert ResumenDiario.objects.filter(estacion=a).count() == 1
    assert ResumenDiario.objects.filter(estacion=b).count() == 1
    assert ResumenDiario.objects.get(estacion=a).fecha == date(2021, 1, 1)


def test_horario_solo_temperatura_media_no_falla():
    estacion = Estacion.objects.create(nombre="Solo media", codigo="test-04")
    df = pd.DataFrame(
        [
            {
                "estacion_id": estacion.id,
                "timestamp": f"2025-01-01T{h:02d}:00:00Z",
                "frecuencia": "H",
                "temperatura_media": t,
            }
            for h, t in [(12, 10.0), (13, 20.0)]
        ]
    )
    derivar_resumenes_diarios(df)
    res = ResumenDiario.objects.get()
    assert res.tmax == 20.0
    assert res.tmin == 10.0
    assert res.tmedia == 15.0


def test_dia_y_hora_misma_corrida_no_falla():
    estacion = Estacion.objects.create(nombre="Mixto", codigo="test-05")
    df = pd.DataFrame(
        [
            {
                "estacion_id": estacion.id,
                "timestamp": "2025-01-01T12:00:00Z",
                "frecuencia": "D",
                "temperatura_maxima": 25.0,
                "temperatura_minima": 10.0,
            },
            {
                "estacion_id": estacion.id,
                "timestamp": "2025-01-01T13:00:00Z",
                "frecuencia": "H",
                "temperatura_media": 30.0,
            },
        ]
    )
    derivar_resumenes_diarios(df)
    res = ResumenDiario.objects.get()
    assert res.origen == "H"


def test_dia_sin_datos_es_null_con_motivo():
    estacion = Estacion.objects.create(nombre="Vacio", codigo="test-06")
    df = pd.DataFrame(
        [
            {
                "estacion_id": estacion.id,
                "timestamp": "2025-01-01T12:00:00Z",
                "frecuencia": "D",
                "motivo_nulo": "Sensor en mantención",
            },
        ]
    )
    derivar_resumenes_diarios(df)
    res = ResumenDiario.objects.get()
    assert res.tmax is None and res.tmin is None and res.tmedia is None
    assert res.motivo_nulo == "Sensor en mantención"


def test_resumen_diario_estacion_inexistente_falla():
    with pytest.raises(Estacion.DoesNotExist):
        resumen_diario("no-existe", "2025-01-01", "2025-01-31")


def test_cadena_medicion_a_resumen_diario():
    est = Estacion.objects.create(nombre="Cadena", codigo="cadena")
    for var, val in [
        ("temperatura_maxima", 25.0),
        ("temperatura_minima", 10.0),
        ("temperatura_media", 17.5),
    ]:
        MedicionHoraria.objects.create(
            estacion=est,
            timestamp="2025-01-01T12:00:00Z",
            variable=var,
            frecuencia="D",
            valor=val,
        )
    call_command("generar_resumenes")
    data = resumen_diario("cadena", "2025-01-01", "2025-01-31")
    assert data["dias"][0]["tmax"] == 25.0
    assert data["dias"][0]["amplitud"] == 15.0


def test_completitud_temporada_sin_lluvia_tiene_observacion():
    est = Estacion.objects.create(nombre="Comp", codigo="comp")
    for dia in (1, 2):
        ResumenDiario.objects.create(
            estacion=est,
            fecha=date(2022, 1, dia),
            temporada="2021-2022",
            tmax=25.0,
            tmin=10.0,
            tmedia=17.0,
        )
    res = completitud_por_temporada("comp")
    assert len(res) == 1
    assert res[0]["variables"]["precipitacion"] == 0
    assert "observacion" in res[0]
    assert res[0]["confiable"] is False


def test_temporadas_y_estaciones():
    est = Estacion.objects.create(nombre="Est", codigo="est", subzona="Z", propietario="P")
    ResumenDiario.objects.create(
        estacion=est, fecha=date(2022, 1, 1), temporada="2021-2022", tmax=25.0, tmin=10.0
    )
    ResumenDiario.objects.create(estacion=est, fecha=date(2019, 1, 1), temporada="2018-2019")
    assert temporadas() == ["2021-2022"]

    data = next(e for e in estaciones() if e["id"] == "est")
    assert data["variables"] == ["tmax", "tmin"]
    assert data["fecha_inicio"] == "2019-01-01"
    assert data["temporadas_disponibles"] == 1
    assert data["calidad_dato"]["confiable"] is False


EJEMPLO = json.loads(
    (settings.BASE_DIR / "docs" / "contrato" / "ejemplo_sprint1.json").read_text(encoding="utf-8")
)


@pytest.fixture
def estacion_contrato():
    est = Estacion.objects.create(
        nombre="Contrato", codigo="cp-test-01", subzona="test", propietario="Casas Patronales"
    )
    ResumenDiario.objects.create(
        estacion=est,
        fecha=date(2024, 1, 25),
        temporada="2023-2024",
        tmax=33.9,
        tmin=12.1,
        tmedia=22.4,
        amplitud_termica=21.8,
        precipitacion=None,
    )
    ResumenDiario.objects.create(
        estacion=est,
        fecha=date(2024, 1, 29),
        temporada="2023-2024",
        motivo_nulo="falla de estación",
    )
    return est


def test_contrato_resumen_diario(estacion_contrato):
    ejemplo = EJEMPLO["resumen_diario"]
    data = resumen_diario("cp-test-01", "2024-01-25", "2024-01-31")
    assert set(data) == set(ejemplo)

    dia_normal = ejemplo["dias"][0]
    dia_nulo = next(d for d in ejemplo["dias"] if "motivo_nulo" in d)
    assert set(data["dias"][0]) == set(dia_normal)
    assert set(data["dias"][1]) == set(dia_nulo)


def test_contrato_completitud_por_temporada(estacion_contrato):
    ejemplo = EJEMPLO["completitud_por_temporada"]
    sin_obs = next(i for i in ejemplo if "observacion" not in i)
    con_obs = next(i for i in ejemplo if "observacion" in i)

    item = completitud_por_temporada("cp-test-01")[0]
    assert set(item) - {"observacion"} == set(sin_obs)
    assert set(item["variables"]) == set(sin_obs["variables"])
    assert item["observacion"] == con_obs["observacion"]  # el fixture no tiene lluvia


def test_contrato_temporadas(estacion_contrato):
    assert isinstance(EJEMPLO["temporadas"], list)
    assert temporadas() == ["2023-2024"]


def test_contrato_estaciones(estacion_contrato):
    ejemplo = EJEMPLO["estaciones"][0]
    data = next(e for e in estaciones() if e["id"] == "cp-test-01")
    assert set(data) == set(ejemplo)
    assert set(data["calidad_dato"]) == set(ejemplo["calidad_dato"])
    assert isinstance(data["temporadas_disponibles"], int)
