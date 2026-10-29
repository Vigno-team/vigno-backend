"""E1C-132: recargas, auditoría y publicación de las correcciones manuales."""

import shutil

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models.query import QuerySet
from rest_framework.test import APIClient

from apps.clima.models import CorreccionManual, Estacion, MedicionHoraria, ResumenDiario
from apps.clima.tests.test_correcciones import crear, dias_json, medir, revertir
from apps.clima.tests.test_ingestar_excel import crear_excel, fila, ingestar
from apps.ingesta.models import RegistroCarga

pytestmark = pytest.mark.django_db


@pytest.fixture
def entorno(settings, tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    for nombre in ("rangos_variables.json", "mapeos_estaciones.json", "validacion_cargas.json"):
        shutil.copyfile(settings.BASE_DIR / "config" / nombre, config / nombre)
    (config / "areas_mapa.json").write_text(
        '{"type":"FeatureCollection","features":[]}', encoding="utf-8"
    )
    settings.BASE_DIR = tmp_path
    settings.DATOS_DIR = tmp_path / "salidas"
    settings.INGESTA_API_KEY = "clave-e132-test"
    estacion, _ = Estacion.objects.update_or_create(
        nombre="San Clemente", defaults={"codigo": "sc", "latitud": -35.5}
    )
    for fecha in ("2025-01-15", "2025-01-17"):
        medir(estacion, fecha, valor=17, temporada=2025)
    return estacion


@pytest.fixture
def cliente(entorno):
    return APIClient(HTTP_X_API_KEY="clave-e132-test")


def dato_corregido(estacion):
    return MedicionHoraria.objects.get(
        estacion=estacion, timestamp__date="2025-01-16", variable="temperatura_media"
    )


def ficha_json(cliente):
    respuesta = cliente.get("/api/v1/datos")
    assert respuesta.status_code == 200
    return next(
        f
        for f in respuesta.json()["ficha_temporada"]
        if f["estacion_id"] == "sc" and f["temporada"] == "2024-2025"
    )


@pytest.mark.parametrize("valor_excel", [None, "error", 80, -16])
def test_excel_invalido_no_pisa_correccion(cliente, entorno, tmp_path, valor_excel):
    correccion = crear(cliente)
    antes = dato_corregido(entorno)
    ruta = crear_excel(tmp_path / "recarga_2025.xlsx", [fila("2025-01-16", valor_excel)])
    ingestar(ruta)
    despues = dato_corregido(entorno)
    assert despues.valor == 21 and despues.origen == "manual"
    assert despues.carga_id == antes.carga_id and not despues.fuera_de_rango
    c = CorreccionManual.objects.get(pk=correccion["id"])
    assert c.estado == "vigente" and c.reemplazada_por_id is None
    assert RegistroCarga.objects.latest("pk").registros_sin_cambio >= 1
    call_command("actualizar_todo", "--sin-satelite")
    assert next(d for d in dias_json() if d["fecha"] == "2025-01-16")["corregido_a_mano"]


@pytest.mark.parametrize("valor_excel", [19, 21])
def test_excel_valido_reemplaza_incluso_el_mismo_valor(cliente, entorno, tmp_path, valor_excel):
    correccion = crear(cliente)
    ruta = crear_excel(tmp_path / "recarga_2025.xlsx", [fila("2025-01-16", valor_excel)])
    ingestar(ruta)
    dato = dato_corregido(entorno)
    carga = RegistroCarga.objects.latest("pk")
    c = CorreccionManual.objects.get(pk=correccion["id"])
    assert (dato.valor, dato.origen, dato.carga_id) == (valor_excel, "excel", carga.pk)
    assert c.estado == "reemplazada" and c.reemplazada_por_id == carga.pk
    assert c.valor_nuevo == 21 and c.autor == "Enóloga de prueba"
    assert revertir(cliente, c.pk).status_code == 409
    bitacora = cliente.get("/api/v1/correcciones?estacion=sc").json()["results"]
    assert next(r for r in bitacora if r["id"] == c.pk)["reemplazada_por"] == carga.pk
    call_command("actualizar_todo", "--sin-satelite")
    assert not next(d for d in dias_json() if d["fecha"] == "2025-01-16")["corregido_a_mano"]
    assert ficha_json(cliente)["dias_corregidos_a_mano"] == 0


@pytest.mark.parametrize("frecuencia", ["D", "H"])
def test_marca_diaria_y_horaria_se_actualiza_y_se_revierte(cliente, entorno, frecuencia):
    medir(entorno, "2025-01-16", valor=17, frecuencia=frecuencia, temporada=2025)
    call_command("generar_resumenes")
    assert not ResumenDiario.objects.get(estacion=entorno, fecha="2025-01-16").corregido_a_mano
    extra = {"hora": "12:00"} if frecuencia == "H" else {}
    c = crear(cliente, frecuencia=frecuencia, **extra)
    assert ResumenDiario.objects.get(estacion=entorno, fecha="2025-01-16").corregido_a_mano
    dia = next(d for d in dias_json() if d["fecha"] == "2025-01-16")
    assert dia["corregido_a_mano"] is True and dia["tmedia"] == 21
    assert ficha_json(cliente)["dias_corregidos_a_mano"] == 1
    respuesta = cliente.get("/api/v1/temporadas/2024-2025", {"estacion": "sc"})
    assert respuesta.status_code == 200
    assert respuesta.json()["dias_corregidos_a_mano"] == 1
    assert revertir(cliente, c["id"]).status_code == 200
    assert not ResumenDiario.objects.get(estacion=entorno, fecha="2025-01-16").corregido_a_mano
    assert ficha_json(cliente)["dias_corregidos_a_mano"] == 0
    assert not next(d for d in dias_json() if d["fecha"] == "2025-01-16")["corregido_a_mano"]


def test_regenerar_actualiza_resumen_existente_y_cuenta_dias_no_correcciones(cliente, entorno):
    crear(cliente)
    crear(cliente, variable="precipitacion", valor_nuevo=4)
    resumen = ResumenDiario.objects.get(estacion=entorno, fecha="2025-01-16")
    ResumenDiario.objects.filter(pk=resumen.pk).update(corregido_a_mano=False)
    call_command("generar_resumenes")
    resumen.refresh_from_db()
    assert resumen.corregido_a_mano
    assert ficha_json(cliente)["dias_corregidos_a_mano"] == 1
    MedicionHoraria.objects.filter(estacion=entorno).update(origen="excel")
    call_command("generar_resumenes")
    resumen.refresh_from_db()
    assert not resumen.corregido_a_mano


def test_manual_se_agrupa_por_estacion_dia_y_todas_las_horas(entorno):
    otra = Estacion.objects.create(nombre="Otra", codigo="otra")
    for estacion in (entorno, otra):
        for fecha in ("2025-01-16", "2025-01-18"):
            for hora in (10, 11):
                medir(estacion, fecha, frecuencia="H", hora=hora)
    dato = MedicionHoraria.objects.filter(estacion=entorno, timestamp__date="2025-01-16").earliest(
        "timestamp"
    )
    dato.origen = "manual"
    dato.save(update_fields=["origen"])
    call_command("generar_resumenes")
    marcados = list(ResumenDiario.objects.filter(corregido_a_mano=True))
    assert len(marcados) == 1
    assert marcados[0].estacion == entorno and marcados[0].fecha.isoformat() == "2025-01-16"


def test_reemplazo_es_atomico_si_falla_la_auditoria(cliente, entorno, tmp_path, monkeypatch):
    c = crear(cliente)
    original_update = QuerySet.update

    def fallar(self, **kwargs):
        if self.model is CorreccionManual:
            raise RuntimeError("Fallo simulado de auditoría")
        return original_update(self, **kwargs)

    monkeypatch.setattr(QuerySet, "update", fallar)
    ruta = crear_excel(tmp_path / "recarga_2025.xlsx", [fila("2025-01-16", 18)])
    with pytest.raises(CommandError, match="Fallo simulado de auditoría"):
        ingestar(ruta)
    dato = dato_corregido(entorno)
    assert (dato.valor, dato.origen) == (21, "manual")
    assert CorreccionManual.objects.get(pk=c["id"]).estado == "vigente"
    assert RegistroCarga.objects.latest("pk").estado == RegistroCarga.ESTADO_FALLIDA


def test_carga_por_api_repetida_conserva_y_archivo_valido_reemplaza(cliente, entorno, tmp_path):
    def subir(ruta):
        return cliente.post(
            "/api/v1/cargas",
            {"archivo": SimpleUploadedFile(ruta.name, ruta.read_bytes()), "estacion": "sc"},
            format="multipart",
        )

    ruta = tmp_path / "san_clemente_2025.xlsx"
    crear_excel(ruta, [fila("2025-01-15"), fila("2025-01-16", None), fila("2025-01-17")])
    assert subir(ruta).status_code == 201
    c = crear(cliente)
    repetida = subir(ruta)
    assert repetida.status_code == 200 and repetida.json()["repetida"]
    assert dato_corregido(entorno).origen == "manual"
    assert next(d for d in dias_json() if d["fecha"] == "2025-01-16")["corregido_a_mano"]
    crear_excel(ruta, [fila("2025-01-15"), fila("2025-01-16", 19), fila("2025-01-17")])
    respuesta = subir(ruta)
    assert respuesta.status_code == 201, respuesta.data
    assert respuesta.json()["recalculo"]["ok"]
    assert dato_corregido(entorno).origen == "excel"
    assert dato_corregido(entorno).valor == 19
    correccion = CorreccionManual.objects.get(pk=c["id"])
    assert correccion.estado == "reemplazada"
    assert correccion.reemplazada_por_id == respuesta.json()["id"]
    assert ficha_json(cliente)["dias_corregidos_a_mano"] == 0
