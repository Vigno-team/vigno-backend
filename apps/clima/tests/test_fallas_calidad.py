import csv
import io
from datetime import date

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.clima.management.commands.exportar_json import exportar
from apps.clima.models import Estacion, MedicionHoraria, ResumenDiario
from apps.clima.tests.test_ingestar_excel import crear_excel, fila, ingestar
from apps.ingesta.models import RegistroCarga

pytestmark = pytest.mark.django_db


@pytest.fixture
def datos(tmp_path):
    estacion = Estacion.objects.update_or_create(nombre="San Clemente", defaults={"codigo": "sc"})[
        0
    ]
    mala = fila("2025-01-15", None)
    mala[2] = 80
    archivo = crear_excel(tmp_path / "fallas.xlsx", [mala, fila("2025-01-17"), fila("fecha mala")])
    ingestar(archivo, temporada=2025)
    return estacion


def consultar(**extra):
    return APIClient().get(
        "/api/v1/calidad/fallas", {"estacion": "sc", "temporada": "2024-2025", **extra}
    )


def test_cuatro_tipos_trazabilidad_y_csv(datos):
    antes = list(MedicionHoraria.objects.values())
    respuesta = consultar().json()
    assert respuesta["resumen"]["por_tipo"] == dict(
        rechazado=1, nulo=1, sin_registro=1, fuera_de_rango=1
    )
    assert respuesta["resumen"]["total"] == 4
    por_tipo = {f["tipo"]: f for f in respuesta["fallas"]}
    assert por_tipo["sin_registro"]["fecha"] == "2025-01-16"
    assert por_tipo["sin_registro"]["valor_original"] is None
    assert por_tipo["nulo"]["motivo"]
    assert por_tipo["fuera_de_rango"]["valor_original"] == 80
    rechazo = por_tipo["rechazado"]
    assert rechazo["fecha"] is None
    assert rechazo["valor_original"] == "fecha mala"
    assert rechazo["fila"] and rechazo["archivo"] == "fallas.xlsx" and rechazo["carga"]
    assert rechazo["criterio_temporada"] == "anio_archivo_fecha_desconocida"
    assert all(f["corregido"] is False for f in respuesta["fallas"])
    filas = list(
        csv.DictReader(io.StringIO(consultar(formato="csv").content.decode()), delimiter=";")
    )
    assert len(filas) == 4
    assert {f["Tipo"] for f in filas} == set(por_tipo)
    assert all(f["Corregido"] == "No" for f in filas)
    assert list(MedicionHoraria.objects.values()) == antes


def test_rechazos_con_fecha_filtran_por_fecha_no_anio_archivo(datos):
    carga = RegistroCarga.objects.get()
    carga.detalle_rechazos = [
        {"fila": 1, "valor_original": "2025-01-16", "motivo": "Duplicada"},
        {"fila": 2, "valor_original": "2023-01-16", "motivo": "Duplicada"},
        {"fila": 3, "valor_original": "00:00", "motivo": "Fecha inválida"},
    ]
    carga.save()
    rechazos = [f for f in consultar().json()["fallas"] if f["tipo"] == "rechazado"]
    assert len(rechazos) == 2
    assert {f["fecha"] for f in rechazos} == {"2025-01-16", None}


def test_sin_datos_no_inventa_un_anio_de_fallas():
    Estacion.objects.create(nombre="Vacía", codigo="sc")
    assert consultar().json()["resumen"]["total"] == 0


def test_csv_neutraliza_formulas(datos):
    carga = RegistroCarga.objects.get()
    carga.detalle_rechazos = [{"fila": 8, "valor_original": "=1+1", "motivo": "Fecha inválida"}]
    carga.save()
    filas = list(
        csv.DictReader(io.StringIO(consultar(formato="csv").content.decode()), delimiter=";")
    )
    assert next(f for f in filas if f["Tipo"] == "rechazado")["Valor original"] == "'=1+1"


def test_pipeline_no_imputa_mediciones_ni_huecos(datos):
    assert MedicionHoraria.objects.count() == 14
    assert list(
        MedicionHoraria.objects.filter(variable="temperatura_media")
        .order_by("timestamp")
        .values_list("valor", flat=True)
    ) == [None, 15]
    assert list(
        MedicionHoraria.objects.filter(variable="temperatura_maxima")
        .order_by("timestamp")
        .values_list("valor", flat=True)
    ) == [80, 20]
    originales = list(
        MedicionHoraria.objects.order_by("pk").values_list("pk", "valor", "timestamp")
    )
    call_command("generar_resumenes")
    call_command("calcular_indices")
    salida = exportar()
    consultar()
    assert (
        list(MedicionHoraria.objects.order_by("pk").values_list("pk", "valor", "timestamp"))
        == originales
    )
    assert not MedicionHoraria.objects.filter(timestamp__date=date(2025, 1, 16)).exists()
    assert not ResumenDiario.objects.filter(fecha=date(2025, 1, 16)).exists()
    primero = ResumenDiario.objects.get(fecha=date(2025, 1, 15))
    assert primero.tmedia is None and primero.tmax is None
    assert primero.tmin == 10 and primero.precipitacion == 0
    assert ResumenDiario.objects.get(fecha=date(2025, 1, 17)).tmedia == 15
    dias = salida["resumen_diario"][0]["dias"]
    assert not any(str(d["fecha"]) == "2025-01-16" for d in dias)
    primero_exportado = next(d for d in dias if str(d["fecha"]) == "2025-01-15")
    assert primero_exportado["tmax"] is None
    assert primero_exportado["tmedia"] is None


def test_rechazos_otra_estacion_y_otro_periodo_no_se_mezclan(datos):
    RegistroCarga.objects.create(
        estacion="Otra estación",
        archivo="otro.xlsx",
        temporada=2025,
        detalle_rechazos=[{"fila": 1, "valor_original": "mala", "motivo": "Fecha inválida"}],
    )
    assert consultar().json()["resumen"]["por_tipo"]["rechazado"] == 1
    assert consultar(temporada="2022-2023").json()["resumen"]["total"] == 0


def test_huecos_no_incluyen_futuro_y_consideran_dias_con_nulos(datos, monkeypatch):
    from apps.clima import fallas_rangos

    localdate = fallas_rangos.timezone.localdate
    monkeypatch.setattr(
        fallas_rangos.timezone,
        "localdate",
        lambda value=None: localdate(value) if value else date(2025, 1, 15),
    )
    assert consultar().json()["resumen"]["por_tipo"]["sin_registro"] == 0


def test_nulo_sin_carga_conserva_motivo(datos):
    MedicionHoraria.objects.filter(valor__isnull=True).update(carga=None, motivo_nulo="Celda vacía")
    nulo = next(f for f in consultar().json()["fallas"] if f["tipo"] == "nulo")
    assert nulo["motivo"] == "Celda vacía"
    assert nulo["archivo"] is None and nulo["carga"] is None
