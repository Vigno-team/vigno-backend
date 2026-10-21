import csv
import io
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.clima.lluvia import eventos_lluvia
from apps.clima.models import Estacion, MedicionHoraria, ResumenDiario
from apps.clima.rangos import MOTIVO_RANGO, cargar_rangos, motivo_fuera_de_rango
from apps.clima.tests.test_ingestar_excel import crear_excel, fila, ingestar


@pytest.mark.parametrize(
    "variable",
    ["tmax", "tmin", "tmedia", "temperatura_maxima", "temperatura_minima", "temperatura_media"],
)
@pytest.mark.parametrize(
    "valor,invalido", [(-15, False), (50, False), (-15.01, True), (50.01, True), (None, False)]
)
def test_limites_temperatura(variable, valor, invalido):
    assert bool(motivo_fuera_de_rango(variable, valor)) is invalido


@pytest.mark.parametrize(
    "frecuencia,valor,invalido",
    [
        ("D", 300, False),
        ("H", 100, False),
        ("D", 300.1, True),
        ("H", 100.1, True),
        ("H", 150, True),
        ("D", 150, False),
        ("D", -1, True),
        ("H", -1, True),
        ("D", 0, False),
        ("H", 0, False),
    ],
)
def test_limites_lluvia(frecuencia, valor, invalido):
    assert bool(motivo_fuera_de_rango("precipitacion", valor, frecuencia)) is invalido


def test_catalogo_configurable_compartido(tmp_path, settings):
    catalogo = cargar_rangos()
    catalogo["tmax"]["max"] = 42
    (tmp_path / "config").mkdir()
    (tmp_path / "config/rangos_variables.json").write_text(json.dumps(catalogo), encoding="utf-8")
    settings.BASE_DIR = tmp_path
    assert motivo_fuera_de_rango("tmax", 43)
    assert motivo_fuera_de_rango("temperatura_maxima", 43)
    assert motivo_fuera_de_rango("humedad_media", 80) is None


@pytest.fixture
def estacion(db):
    return Estacion.objects.update_or_create(nombre="San Clemente", defaults={"codigo": "sc"})[0]


def cargar(tmp_path, estacion, temp=80, lluvia=-1, temporada=2025):
    valores = fila("2025-01-15", 20)
    valores[2] = temp
    valores[-1] = lluvia
    archivo = crear_excel(tmp_path / "rangos.xlsx", [valores])
    ingestar(archivo, temporada=temporada)
    return archivo


def test_excel_conserva_original_excluye_resumen_y_publica_reporte(tmp_path, estacion):
    cargar(tmp_path, estacion)
    tmax = MedicionHoraria.objects.get(variable="temperatura_maxima")
    assert tmax.valor == 80
    assert tmax.fuera_de_rango is True
    assert MOTIVO_RANGO in tmax.motivo_fuera_de_rango
    assert tmax.motivo_nulo is None
    call_command("generar_resumenes")
    resumen = ResumenDiario.objects.get()
    assert resumen.tmax is None and resumen.precipitacion is None
    assert resumen.tmin == 10 and resumen.tmedia == 20
    assert resumen.amplitud_termica is None
    assert resumen.motivo_nulo == MOTIVO_RANGO
    assert resumen.confiable is False
    respuesta = APIClient().get(
        "/api/v1/calidad/fallas", {"estacion": "sc", "temporada": "2024-2025"}
    )
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["resumen"]["total"] == 2
    assert set(datos["tipos_incluidos"]) == {"rechazado", "nulo", "sin_registro", "fuera_de_rango"}
    marca = next(f for f in datos["fallas"] if f["variable"] == "temperatura_maxima")
    assert marca["valor_original"] == 80
    assert marca["carga"] == tmax.carga_id
    assert marca["archivo"] == "rangos.xlsx"
    assert marca["fecha"] == "2025-01-15"
    assert marca["corregido"] is False
    assert marca["tipo"] == "fuera_de_rango"
    csv_response = APIClient().get(
        "/api/v1/calidad/fallas", {"estacion": "sc", "temporada": "2024-2025", "formato": "csv"}
    )
    assert csv_response.status_code == 200
    filas = list(csv.DictReader(io.StringIO(csv_response.content.decode()), delimiter=";"))
    assert len(filas) == 2
    assert set(f["Valor original"] for f in filas) == {"80.0", "-1.0"}


def test_recarga_idempotente_y_correccion_elimina_marca(tmp_path, estacion):
    cargar(tmp_path, estacion)
    total = MedicionHoraria.objects.count()
    cargar(tmp_path, estacion)
    assert MedicionHoraria.objects.count() == total
    assert MedicionHoraria.objects.filter(fuera_de_rango=True).count() == 2
    cargar(tmp_path, estacion, temp=30, lluvia=0)
    assert MedicionHoraria.objects.filter(fuera_de_rango=True).count() == 0
    assert not MedicionHoraria.objects.exclude(motivo_fuera_de_rango=None).exists()
    call_command("generar_resumenes")
    assert ResumenDiario.objects.get().tmax == 30
    assert ResumenDiario.objects.get().motivo_nulo is None


def test_archivo_antiguo_no_cambia_marcas_ni_valor(tmp_path, estacion):
    cargar(tmp_path, estacion, temp=30, lluvia=0, temporada=2026)
    cargar(tmp_path, estacion, temporada=2025)
    assert MedicionHoraria.objects.get(variable="temperatura_maxima").valor == 30
    assert not MedicionHoraria.objects.filter(fuera_de_rango=True).exists()


def test_revalida_valor_igual_que_antes_no_tenia_marca(tmp_path, estacion):
    cargar(tmp_path, estacion)
    MedicionHoraria.objects.update(fuera_de_rango=False, motivo_fuera_de_rango=None)
    cargar(tmp_path, estacion)
    assert MedicionHoraria.objects.filter(fuera_de_rango=True).count() == 2


@pytest.mark.parametrize(
    "variable,valor,campo",
    [
        ("temperatura_media", 80, "tmedia"),
        ("temperatura_maxima", 80, "tmax"),
        ("temperatura_minima", -30, "tmin"),
        ("precipitacion", 101, "precipitacion"),
    ],
)
def test_horario_no_oculta_outlier_con_otras_horas_validas(estacion, variable, valor, campo):
    for hora in range(24):
        for v, normal in [
            ("temperatura_media", 20),
            ("temperatura_maxima", 30),
            ("temperatura_minima", 10),
            ("precipitacion", 1),
        ]:
            numero = valor if hora == 12 and v == variable else normal
            motivo = motivo_fuera_de_rango(v, numero, "H")
            MedicionHoraria.objects.create(
                estacion=estacion,
                timestamp=datetime(2025, 1, 15, hora, tzinfo=ZoneInfo("America/Santiago")),
                variable=v,
                frecuencia="H",
                valor=numero,
                fuera_de_rango=bool(motivo),
                motivo_fuera_de_rango=motivo,
            )
    call_command("generar_resumenes")
    resumen = ResumenDiario.objects.get()
    assert getattr(resumen, campo) is None
    assert resumen.motivo_nulo == MOTIVO_RANGO
    if variable == "temperatura_media":
        assert resumen.tmax is None and resumen.tmin is None
        assert resumen.horas_validas == 23
    if variable == "precipitacion":
        eventos = eventos_lluvia(estacion, "2025-01-15", "2025-01-15")
        assert sum(e["total_mm"] for e in eventos["eventos"]) == 23


def test_revalidar_historico_no_modifica_valores_y_es_idempotente(tmp_path, estacion):
    cargar(tmp_path, estacion)
    MedicionHoraria.objects.update(fuera_de_rango=False, motivo_fuera_de_rango=None)
    originales = list(MedicionHoraria.objects.order_by("pk").values_list("valor", flat=True))
    call_command("validar_rangos")
    assert MedicionHoraria.objects.filter(fuera_de_rango=True).count() == 2
    salida = io.StringIO()
    call_command("validar_rangos", stdout=salida)
    assert "Marcas actualizadas: 0" in salida.getvalue()
    assert originales == list(
        MedicionHoraria.objects.order_by("pk").values_list("valor", flat=True)
    )


def test_reporte_filtra_estacion_temporada_y_valida_consulta(tmp_path, estacion):
    cargar(tmp_path, estacion)
    otro = Estacion.objects.create(nombre="Otra", codigo="otra")
    cliente = APIClient()
    for codigo, temporada in [("otra", "2024-2025"), ("sc", "2023-2024")]:
        r = cliente.get("/api/v1/calidad/fallas", {"estacion": codigo, "temporada": temporada})
        assert r.json()["resumen"]["total"] == 0
    assert otro.pk != estacion.pk
    for parametros, estado in [
        ({}, 400),
        ({"estacion": "sc", "temporada": "2024-2026"}, 400),
        ({"estacion": "no-existe", "temporada": "2024-2025"}, 404),
        ({"estacion": "sc", "temporada": "2024-2025", "formato": "xml"}, 400),
    ]:
        assert cliente.get("/api/v1/calidad/fallas", parametros).status_code == estado


def test_recalculo_no_deja_indice_obsoleto_al_quedar_sin_datos(estacion):
    from datetime import date

    from apps.clima.indices import calcular_indices_temporada
    from apps.clima.models import IndiceClimatico

    ResumenDiario.objects.create(
        estacion=estacion,
        fecha=date(2025, 1, 15),
        temporada="2024-2025",
        tmax=80,
        tmin=10,
        tmedia=45,
    )
    calcular_indices_temporada(estacion, "2024-2025")
    assert IndiceClimatico.objects.filter(estacion=estacion, indice="Huglin").exists()
    ResumenDiario.objects.filter(estacion=estacion).update(
        tmax=None, tmin=None, tmedia=None, motivo_nulo=MOTIVO_RANGO
    )
    calcular_indices_temporada(estacion, "2024-2025")
    assert not IndiceClimatico.objects.filter(estacion=estacion).exists()


def test_lluvia_horaria_marcada_sin_temperatura_tambien_genera_motivo(estacion):
    MedicionHoraria.objects.create(
        estacion=estacion,
        timestamp=datetime(2025, 1, 15, 12, tzinfo=ZoneInfo("America/Santiago")),
        variable="precipitacion",
        frecuencia="H",
        valor=-1,
        fuera_de_rango=True,
        motivo_fuera_de_rango=MOTIVO_RANGO,
    )
    call_command("generar_resumenes")
    r = ResumenDiario.objects.get()
    assert r.precipitacion is None and r.motivo_nulo == MOTIVO_RANGO


@pytest.mark.parametrize(
    "frecuencia,horas,confiable", [("D", 1, True), ("H", 24, True), ("H", 2, False)]
)
def test_lluvia_invalida_conserva_confiabilidad_termica(estacion, frecuencia, horas, confiable):
    from apps.clima.services import resumen_diario

    for hora in range(horas):
        for variable, valor in [
            ("temperatura_maxima", 25),
            ("temperatura_minima", 10),
            ("temperatura_media", 18),
            ("precipitacion", -1),
        ]:
            motivo = motivo_fuera_de_rango(variable, valor, frecuencia)
            MedicionHoraria.objects.create(
                estacion=estacion,
                timestamp=datetime(
                    2025,
                    1,
                    15,
                    hora if frecuencia == "H" else 12,
                    tzinfo=ZoneInfo("America/Santiago"),
                ),
                variable=variable,
                frecuencia=frecuencia,
                valor=valor,
                fuera_de_rango=bool(motivo),
                motivo_fuera_de_rango=motivo,
            )
    call_command("generar_resumenes")
    resumen = ResumenDiario.objects.get()
    assert resumen.confiable is confiable
    assert resumen.precipitacion is None
    assert (resumen.tmax, resumen.tmin, resumen.tmedia) == (25, 10, 18)
    assert resumen.motivo_nulo == MOTIVO_RANGO
    dia = resumen_diario(estacion, "2025-01-15", "2025-01-15")["dias"][0]
    assert dia["motivo_nulo"] == MOTIVO_RANGO
    assert dia["tmax"] == 25 and dia["precipitacion"] is None
