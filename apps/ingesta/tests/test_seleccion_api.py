"""Selección de Excel: permisos, reversibilidad, procedencia y recálculo real."""

import json
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from rest_framework.test import APIClient

from apps.auditoria.models import RegistroAuditoria
from apps.auditoria.registro import Accion
from apps.clima.models import MedicionHoraria, ResumenDiario
from apps.clima.tests.test_ingestar_excel import crear_excel, fila
from apps.ingesta import views
from apps.ingesta.models import RegistroCarga

pytestmark = pytest.mark.django_db
URL = "/api/v1/cargas"
ESTACION = "cp-san-clemente-01"
TEMPERATURAS = ["temperatura_maxima", "temperatura_media", "temperatura_minima"]


@pytest.fixture(autouse=True)
def entorno(settings, tmp_path, monkeypatch):
    settings.DATOS_DIR = tmp_path / "datos"
    monkeypatch.setattr(views, "_recalcular", lambda: {"ok": True})


def subir(cliente, ruta, variables=None, query=""):
    ruta = Path(ruta)
    datos = {"archivo": SimpleUploadedFile(ruta.name, ruta.read_bytes()), "estacion": ESTACION}
    if variables is not None:
        datos["variables"] = json.dumps(variables)
    return cliente.post(URL + query, datos, format="multipart")


def excel(tmp_path, nombre="datos_2025.xlsx", temp=15):
    return crear_excel(tmp_path / nombre, [fila("2025-01-10", temp), fila("2025-01-11", temp)])


def cambiar(cliente, pk, excluidas):
    return cliente.patch(f"{URL}/{pk}", {"variables_excluidas": excluidas}, format="json")


def test_diagnostico_tambien_si_una_columna_impide_la_carga(cliente_admin, tmp_path):
    ruta = crear_excel(
        tmp_path / "fallas_2025.xlsx", [fila("2025-01-10", None), fila("2025-01-11", "error")]
    )
    r = subir(cliente_admin, ruta, query="?solo_validar=1")
    assert r.status_code == 422
    media = next(c for c in r.json()["columnas"] if c["variable"] == "temperatura_media")
    assert media["filas_vacias"] == 1
    assert media["filas_no_numericas"] == 1
    assert media["porcentaje_valido"] == 0
    assert "winkler" in media["indicadores"]
    assert not RegistroCarga.objects.exists()
    assert not MedicionHoraria.objects.exists()


def test_confirmar_solo_humedad_no_toca_temperatura_existente(cliente_admin, tmp_path):
    primera = subir(cliente_admin, excel(tmp_path)).json()
    temperatura = MedicionHoraria.objects.filter(variable="temperatura_media").first()
    segunda = subir(cliente_admin, excel(tmp_path, "nuevo_2025.xlsx", temp=45), ["humedad_media"])
    assert segunda.status_code == 201, segunda.json()
    temperatura.refresh_from_db()
    assert temperatura.valor == 15
    assert temperatura.carga_id == primera["id"]
    assert segunda.json()["variables_procesadas"] == ["humedad_media"]


def test_humedad_sola_con_temperaturas_invalidas_se_publica(cliente_admin, tmp_path, monkeypatch):
    def recalcular():
        call_command("actualizar_todo", "--sin-satelite")
        return {"ok": True}

    monkeypatch.setattr(views, "_recalcular", recalcular)
    ruta = crear_excel(
        tmp_path / "humedad_2025.xlsx", [["2025-01-10", "error", None, None, 65, 800, 4, 0, 0]]
    )
    r = subir(cliente_admin, ruta, ["humedad_media"])
    assert r.status_code == 201, r.json()
    assert set(MedicionHoraria.objects.values_list("variable", flat=True)) == {"humedad_media"}
    resumen = ResumenDiario.objects.get()
    assert resumen.humedad_media == 65
    assert resumen.tmedia is None
    datos = cliente_admin.get("/api/v1/datos").json()
    texto = json.dumps(datos)
    assert '"humedad_media": 65.0' in texto


def test_excluir_y_reincluir_recalcula_winkler_y_conserva_original(
    cliente_admin, tmp_path, monkeypatch
):
    def recalcular():
        call_command("actualizar_todo", "--sin-satelite")
        return {"ok": True}

    monkeypatch.setattr(views, "_recalcular", recalcular)
    creada = subir(cliente_admin, excel(tmp_path)).json()
    from apps.clima.resultados import ficha_temporada

    estacion = MedicionHoraria.objects.first().estacion
    anterior = ficha_temporada(estacion, "2024-2025")
    assert anterior["indices"]["winkler"]["valor"] == 10
    r = cambiar(cliente_admin, creada["id"], TEMPERATURAS)
    assert r.status_code == 200, r.json()
    assert MedicionHoraria.objects.filter(variable__in=TEMPERATURAS, excluido=True).count() == 6
    assert MedicionHoraria.objects.filter(variable="temperatura_media").first().valor == 15
    assert ResumenDiario.objects.filter(tmedia__isnull=False).count() == 0
    sin_temperatura = ficha_temporada(estacion, "2024-2025")
    assert sin_temperatura["indices"]["winkler"]["valor"] is None
    assert sin_temperatura["indices"]["winkler"]["motivo_nulo"]
    assert cliente_admin.get("/api/v1/datos").status_code == 200
    assert cambiar(cliente_admin, creada["id"], []).status_code == 200
    assert ficha_temporada(estacion, "2024-2025") == anterior
    assert ResumenDiario.objects.filter(tmedia=15).count() == 2
    auditoria = RegistroAuditoria.objects.filter(accion=Accion.CARGA_SELECCION).earliest("pk")
    assert auditoria.valor_anterior["variables_excluidas"] == []
    assert auditoria.valor_nuevo["variables_excluidas"] == sorted(TEMPERATURAS)
    assert auditoria.usuario.email == "admin@vigno.cl"


@pytest.mark.parametrize("cliente", ["cliente_con_token", "cliente_lector"])
def test_editor_y_lector_no_seleccionan(cliente, request, cliente_admin, tmp_path):
    creada = subir(cliente_admin, excel(tmp_path)).json()
    api = request.getfixturevalue(cliente)
    assert cambiar(api, creada["id"], TEMPERATURAS).status_code == 403
    assert subir(api, excel(tmp_path), ["humedad_media"]).status_code == 403
    assert not MedicionHoraria.objects.filter(excluido=True).exists()


def test_sin_token_patch_401_y_catalogo_autenticado(cliente_admin, tmp_path):
    creada = subir(cliente_admin, excel(tmp_path)).json()
    assert cambiar(APIClient(), creada["id"], []).status_code == 401
    assert APIClient().get("/api/v1/variables").status_code == 401
    r = cliente_admin.get("/api/v1/variables")
    assert r.status_code == 200
    assert r.json()["indicadores"]["winkler"] == [
        ["temperatura_media"],
        ["temperatura_maxima", "temperatura_minima"],
    ]
    assert (
        next(v for v in r.json()["variables"] if v["variable"] == "humedad_media")["indicadores"]
        == []
    )


@pytest.mark.parametrize("excluidas", [None, "temperatura_media", ["no_existe"], [2]])
def test_seleccion_invalida_no_modifica(cliente_admin, tmp_path, excluidas):
    creada = subir(cliente_admin, excel(tmp_path)).json()
    assert cambiar(cliente_admin, creada["id"], excluidas).status_code == 400
    assert not MedicionHoraria.objects.filter(excluido=True).exists()


def test_exclusion_no_afecta_reemplazos_o_manual(cliente_admin, tmp_path):
    primera = subir(cliente_admin, excel(tmp_path)).json()
    subir(cliente_admin, excel(tmp_path, "nuevo_2025.xlsx", 18))
    manual = MedicionHoraria.objects.filter(variable="temperatura_maxima").first()
    manual.origen = "manual"
    manual.save()
    assert cambiar(cliente_admin, primera["id"], TEMPERATURAS).status_code == 200
    assert not MedicionHoraria.objects.filter(variable="temperatura_media", excluido=True).exists()
    manual.refresh_from_db()
    assert not manual.excluido


def test_reincluir_no_guardadas_lee_original_sin_pisar_otras_cargas(cliente_admin, tmp_path):
    ruta = excel(tmp_path)
    primera = subir(cliente_admin, ruta, ["humedad_media"]).json()
    assert MedicionHoraria.objects.count() == 2
    assert cambiar(cliente_admin, primera["id"], []).status_code == 200
    assert MedicionHoraria.objects.count() == 14
    assert MedicionHoraria.objects.filter(carga_id=primera["id"]).count() == 14
    assert set(RegistroCarga.objects.get(pk=primera["id"]).variables_procesadas) == {
        "humedad_media",
        "radiacion_maxima",
        "viento_maximo",
        "precipitacion",
        *TEMPERATURAS,
    }


def test_original_faltante_devuelve_conflicto_sin_cambios(cliente_admin, tmp_path, settings):
    primera = subir(cliente_admin, excel(tmp_path), ["humedad_media"]).json()
    for archivo in (settings.DATOS_DIR / "cargas").iterdir():
        archivo.unlink()
    assert cambiar(cliente_admin, primera["id"], []).status_code == 409
    assert MedicionHoraria.objects.count() == 2
    assert RegistroCarga.objects.get().variables_procesadas == ["humedad_media"]


def test_legacy_sin_fk_se_vincula_por_estacion_y_fechas(cliente_admin, tmp_path):
    primera = subir(cliente_admin, excel(tmp_path)).json()
    MedicionHoraria.objects.update(carga=None)
    RegistroCarga.objects.update(variables_procesadas=[], variables_excluidas=[])
    assert cambiar(cliente_admin, primera["id"], TEMPERATURAS).status_code == 200
    assert MedicionHoraria.objects.filter(carga_id=primera["id"]).count() == 14
    assert MedicionHoraria.objects.filter(excluido=True).count() == 6


def test_legacy_solapado_no_inventa_procedencia(cliente_admin, tmp_path):
    primera = subir(cliente_admin, excel(tmp_path)).json()
    original = RegistroCarga.objects.get()
    RegistroCarga.objects.create(
        archivo="antiguo.xlsx",
        estacion=original.estacion,
        fecha_desde=original.fecha_desde,
        fecha_hasta=original.fecha_hasta,
    )
    MedicionHoraria.objects.update(carga=None)
    assert cambiar(cliente_admin, primera["id"], TEMPERATURAS).status_code == 409
    assert not MedicionHoraria.objects.filter(excluido=True).exists()
    assert not MedicionHoraria.objects.filter(carga__isnull=False).exists()


def test_reinclusion_respeta_datos_ingresados_despues(cliente_admin, tmp_path):
    primera = subir(cliente_admin, excel(tmp_path), ["humedad_media"]).json()
    segunda = subir(cliente_admin, excel(tmp_path, "posterior_2025.xlsx", 19)).json()
    assert cambiar(cliente_admin, primera["id"], []).status_code == 200
    temperaturas = MedicionHoraria.objects.filter(variable="temperatura_media")
    assert set(temperaturas.values_list("valor", flat=True)) == {19}
    assert set(temperaturas.values_list("carga_id", flat=True)) == {segunda["id"]}


def test_no_se_guarda_el_cambio_si_falla_la_bitacora(cliente_admin, tmp_path, monkeypatch):
    from apps.ingesta import seleccion

    primera = subir(cliente_admin, excel(tmp_path)).json()

    def fallar(*args, **kwargs):
        raise RuntimeError("Bitácora no disponible")

    monkeypatch.setattr(seleccion, "registrar", fallar)
    with pytest.raises(RuntimeError, match="Bitácora no disponible"):
        cambiar(cliente_admin, primera["id"], TEMPERATURAS)
    assert RegistroCarga.objects.get().variables_excluidas == []
    assert not MedicionHoraria.objects.filter(excluido=True).exists()


def test_una_estacion_renombrada_conserva_la_procedencia(cliente_admin, tmp_path):
    primera = subir(cliente_admin, excel(tmp_path)).json()
    estacion = MedicionHoraria.objects.first().estacion
    estacion.nombre = "Predio nuevo"
    estacion.save()
    assert cambiar(cliente_admin, primera["id"], TEMPERATURAS).status_code == 200
    assert MedicionHoraria.objects.filter(excluido=True).count() == 6


def test_omitir_variables_reprocesa_todas_despues_de_carga_parcial(cliente_admin, tmp_path):
    ruta = excel(tmp_path)
    assert subir(cliente_admin, ruta, ["humedad_media"]).status_code == 201
    assert subir(cliente_admin, ruta).status_code == 201
    assert MedicionHoraria.objects.count() == 14
