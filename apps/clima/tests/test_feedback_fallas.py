import pandas as pd
import pytest
from rest_framework.test import APIClient

from apps.clima.management.commands.ingestar_excel import Command
from apps.clima.models import Estacion, MedicionHoraria
from apps.clima.tests.test_ingestar_excel import crear_excel, fila, fila_vacia, ingestar
from apps.ingesta.models import RegistroCarga

pytestmark = pytest.mark.django_db


def reporte():
    return (
        APIClient()
        .get("/api/v1/calidad/fallas", {"estacion": "sc", "temporada": "2024-2025"})
        .json()
    )


@pytest.fixture
def estacion():
    return Estacion.objects.update_or_create(nombre="San Clemente", defaults={"codigo": "sc"})[0]


def test_separaciones_vacias_se_cuentan_sin_rechazo_y_conservan_fila(tmp_path, estacion):
    archivo = crear_excel(
        tmp_path / "plantilla.xlsx",
        [
            fila("2025-01-15"),
            fila_vacia(None),
            fila_vacia("   "),
            fila(None, 18),
            fila("00:00:00", 19),
            fila("2025-01-17"),
        ],
    )
    ingestar(archivo, temporada=2025)
    carga = RegistroCarga.objects.get()
    assert carga.filas_vacias_ignoradas == 2
    assert carga.filas_rechazadas == 2
    assert carga.filas_aceptadas == 2
    assert carga.filas_leidas == 6
    assert [r["fila"] for r in carga.detalle_rechazos] == [11, 12]
    assert all(
        r["motivo"] == "Fecha vacía o inválida en una fila con datos"
        for r in carga.detalle_rechazos
    )
    assert reporte()["resumen"]["por_tipo"]["rechazado"] == 2


def test_plantilla_solo_vacia_se_limpia_sin_error():
    df = pd.DataFrame({"fecha": [None, "  "], "temp": [None, " "]})
    resultado = Command()._limpiar_y_rechazar(
        df, {"timestamp": "fecha", "temperatura_media": "temp"}, "D", "America/Santiago", 8
    )
    assert resultado.df_limpio.empty
    assert resultado.rechazos == []
    assert resultado.filas_vacias_ignoradas == 2


def test_recarga_no_duplica_y_correccion_reemplaza_rechazos(tmp_path, estacion):
    archivo = crear_excel(
        tmp_path / "recarga.xlsx", [fila("2025-01-15"), fila("00:00:00"), fila("2025-01-15")]
    )
    ingestar(archivo, temporada=2025)
    ingestar(archivo, temporada=2025)
    assert reporte()["resumen"]["por_tipo"]["rechazado"] == 2
    ultima = RegistroCarga.objects.latest("pk")
    assert {f["carga"] for f in reporte()["fallas"] if f["tipo"] == "rechazado"} == {ultima.pk}
    crear_excel(tmp_path / "recarga.xlsx", [fila("2025-01-15")])
    ingestar(archivo, temporada=2025)
    assert reporte()["resumen"]["por_tipo"]["rechazado"] == 0


def test_carga_fallida_no_oculta_ultima_exitosa(tmp_path, estacion):
    ingestar(
        crear_excel(tmp_path / "correcta.xlsx", [fila("2025-01-15"), fila("00:00:00")]),
        temporada=2025,
    )
    RegistroCarga.objects.create(
        estacion=estacion.nombre,
        archivo="fallida.xlsx",
        temporada=2025,
        estado="FALLIDA",
        detalle_rechazos=[],
    )
    assert reporte()["resumen"]["por_tipo"]["rechazado"] == 1


def test_legacy_nat_y_futuras_no_son_fallas_pero_fecha_mal_escrita_si(estacion):
    RegistroCarga.objects.create(
        estacion=estacion.nombre,
        archivo="2025.xlsx",
        temporada=2025,
        detalle_rechazos=[
            {"fila": 1, "valor_original": "NaT", "motivo": "Fecha inválida"},
            {
                "fila": 2,
                "valor_original": "2025-01-30",
                "motivo": "Fecha futura o sin datos posteriores",
            },
            {"fila": 3, "valor_original": "00:00:00", "motivo": "Fecha inválida"},
            {
                "fila": 4,
                "valor_original": "NaT",
                "motivo": "Fecha vacía o inválida en una fila con datos",
            },
        ],
    )
    assert {f["fila"] for f in reporte()["fallas"]} == {3, 4}


def test_nulos_solo_dentro_periodo_con_valores(tmp_path, estacion):
    archivo = crear_excel(
        tmp_path / "inicio.xlsx",
        [
            fila_vacia("2025-01-01"),
            fila("2025-01-15"),
            fila_vacia("2025-01-16"),
            fila("2025-01-17"),
            fila_vacia("2025-01-18"),
        ],
    )
    ingestar(archivo, temporada=2025)
    nulos = [f for f in reporte()["fallas"] if f["tipo"] == "nulo"]
    assert len(nulos) == 7
    assert {f["fecha"] for f in nulos} == {"2025-01-16"}
    assert reporte()["resumen"]["por_tipo"]["rechazado"] == 0
    assert MedicionHoraria.objects.filter(timestamp__date="2025-01-01").count() == 7


def test_solo_nulos_no_crean_periodo_ni_fallas(tmp_path, estacion):
    ingestar(
        crear_excel(tmp_path / "vacia.xlsx", [fila_vacia("2025-01-01"), fila_vacia("2025-01-03")]),
        temporada=2025,
    )
    assert reporte()["resumen"]["total"] == 0
