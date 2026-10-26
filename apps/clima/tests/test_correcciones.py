import csv
import io
import shutil
from datetime import date, datetime, time, timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.clima import correcciones
from apps.clima.models import (
    CorreccionManual,
    Estacion,
    IndiceClimatico,
    MedicionHoraria,
    ResumenDiario,
)
from apps.clima.tests.test_ingestar_excel import crear_excel, fila, ingestar
from apps.ingesta.models import RegistroCarga

pytestmark = pytest.mark.django_db
URL = "/api/v1/correcciones"
CLAVE = "clave-solo-para-tests"


def medir(
    estacion, fecha, variable="temperatura_media", valor=17, frecuencia="D", hora=12, **extra
):
    return MedicionHoraria.objects.create(
        estacion=estacion,
        timestamp=timezone.make_aware(datetime.combine(date.fromisoformat(fecha), time(hora))),
        variable=variable,
        valor=valor,
        frecuencia=frecuencia,
        **extra,
    )


@pytest.fixture
def entorno(settings, tmp_path):
    configuracion = tmp_path / "config"
    configuracion.mkdir()
    for nombre in ("rangos_variables.json", "mapeos_estaciones.json"):
        shutil.copyfile(settings.BASE_DIR / "config" / nombre, configuracion / nombre)
    (configuracion / "areas_mapa.json").write_text(
        '{"type":"FeatureCollection","features":[]}', encoding="utf-8"
    )
    settings.BASE_DIR = tmp_path
    settings.DATOS_DIR = tmp_path / "salidas"
    settings.INGESTA_API_KEY = CLAVE
    estacion, _ = Estacion.objects.update_or_create(
        nombre="San Clemente", defaults={"codigo": "sc", "latitud": -35.5}
    )
    for fecha in ("2025-01-15", "2025-01-17"):
        for variable, valor in (
            ("temperatura_media", 17),
            ("temperatura_maxima", 25),
            ("temperatura_minima", 10),
            ("precipitacion", 0),
        ):
            medir(estacion, fecha, variable, valor, temporada=2025)
    return estacion


@pytest.fixture
def cliente(entorno):
    return APIClient(HTTP_X_API_KEY=CLAVE)


def entrada(**extra):
    return {
        "estacion": "sc",
        "fecha": "2025-01-16",
        "variable": "tmedia",
        "frecuencia": "D",
        "valor_nuevo": 21,
        "autor": "Enóloga de prueba",
        "motivo": "Planilla manual del predio",
        **extra,
    }


def crear(cliente, **extra):
    respuesta = cliente.post(URL, entrada(**extra), format="json")
    assert respuesta.status_code == 201, respuesta.data
    assert respuesta.json()["actualizacion"] == {"ok": True}
    return respuesta.json()["correccion"]


def revertir(cliente, pk):
    return cliente.post(
        f"{URL}/{pk}/revertir",
        {"autor": "Revisor", "motivo": "Se anuló la planilla manual"},
        format="json",
    )


def dias_json():
    respuesta = APIClient().get("/api/v1/datos")
    assert respuesta.status_code == 200
    return next(e["dias"] for e in respuesta.json()["resumen_diario"] if e["estacion_id"] == "sc")


def fallas(**extra):
    return APIClient().get(
        "/api/v1/calidad/fallas", {"estacion": "sc", "temporada": "2024-2025", **extra}
    )


def test_hueco_se_reintegra_sin_imputar_y_reversion_elimina_el_resumen(cliente, entorno):
    originales = list(MedicionHoraria.objects.order_by("pk").values())
    call_command("actualizar_todo", "--sin-satelite")
    indice = IndiceClimatico.objects.get(estacion=entorno, indice="Winkler").valor
    correccion = crear(cliente)
    assert correccion["autor"] == "Enóloga de prueba"
    assert correccion["motivo"] == "Planilla manual del predio"
    assert correccion["valor_anterior"] is None and correccion["hora"] is None
    nuevo = MedicionHoraria.objects.get(timestamp__date="2025-01-16")
    assert nuevo.origen == "manual" and nuevo.valor == 21
    assert timezone.localtime(nuevo.timestamp).hour == 12
    assert nuevo.variable == "temperatura_media"
    assert list(MedicionHoraria.objects.exclude(pk=nuevo.pk).order_by("pk").values()) == originales
    dia = next(d for d in dias_json() if d["fecha"] == "2025-01-16")
    assert dia["tmedia"] == 21 and dia["tmax"] is None and dia["precipitacion"] is None
    assert IndiceClimatico.objects.get(estacion=entorno, indice="Winkler").valor == indice + 11
    assert (
        next(f for f in fallas().json()["fallas"] if f["tipo"] == "sin_registro")["corregido"]
        is True
    )
    assert revertir(cliente, correccion["id"]).status_code == 200
    assert not MedicionHoraria.objects.filter(timestamp__date="2025-01-16").exists()
    assert not ResumenDiario.objects.filter(fecha="2025-01-16").exists()
    assert not any(d["fecha"] == "2025-01-16" for d in dias_json())
    assert IndiceClimatico.objects.get(estacion=entorno, indice="Winkler").valor == indice
    assert (
        next(f for f in fallas().json()["fallas"] if f["tipo"] == "sin_registro")["corregido"]
        is False
    )
    assert revertir(cliente, correccion["id"]).status_code == 409


@pytest.mark.parametrize(
    "valor,marca,motivo",
    [
        (None, False, "Valor no numérico en origen: 'error'"),
        (80, True, "Valor fuera de rango físico"),
    ],
)
def test_conserva_y_restaura_null_o_outlier_con_su_carga(cliente, entorno, valor, marca, motivo):
    carga = RegistroCarga.objects.create(
        estacion=entorno.nombre, archivo="estacion.xlsx", temporada=2025
    )
    dato = medir(
        entorno,
        "2025-01-16",
        valor=valor,
        fuera_de_rango=marca,
        motivo_nulo=motivo if not marca else None,
        motivo_fuera_de_rango=motivo if marca else None,
        carga=carga,
        temporada=2025,
    )
    original = {k: getattr(dato, k) for k in correcciones.CAMPOS_DATO}
    correccion = crear(cliente)
    dato.refresh_from_db()
    assert dato.valor == 21 and dato.origen == "manual" and not dato.fuera_de_rango
    assert dato.motivo_nulo is None and dato.motivo_fuera_de_rango is None
    problema = next(
        f for f in fallas().json()["fallas"] if f["tipo"] == ("fuera_de_rango" if marca else "nulo")
    )
    assert problema["corregido"] is True and problema["valor_original"] == valor
    assert problema["carga"] == carga.pk and problema["archivo"] == "estacion.xlsx"
    filas = list(csv.DictReader(io.StringIO(fallas(formato="csv").content.decode()), delimiter=";"))
    assert any(f["Corregido"] == "Sí" for f in filas)
    assert revertir(cliente, correccion["id"]).status_code == 200
    dato.refresh_from_db()
    assert {k: getattr(dato, k) for k in correcciones.CAMPOS_DATO} == original
    assert next(d for d in dias_json() if d["fecha"] == "2025-01-16")["tmedia"] is None
    guardada = CorreccionManual.objects.get(pk=correccion["id"])
    assert guardada.revertida_por == "Revisor" and guardada.motivo_reversion
    assert guardada.revertida_en is not None


def test_reemplazo_y_reversion_respetan_la_cadena(cliente):
    uno = crear(cliente)
    dos = crear(cliente, valor_nuevo=22, autor="Otra persona")
    assert dos["anterior"] == uno["id"] and dos["valor_anterior"] == 21
    assert CorreccionManual.objects.get(pk=uno["id"]).estado == "reemplazada"
    assert revertir(cliente, uno["id"]).status_code == 409
    assert revertir(cliente, dos["id"]).status_code == 200
    assert CorreccionManual.objects.get(pk=uno["id"]).estado == "vigente"
    assert MedicionHoraria.objects.get(timestamp__date="2025-01-16").valor == 21
    assert revertir(cliente, uno["id"]).status_code == 200
    assert not MedicionHoraria.objects.filter(timestamp__date="2025-01-16").exists()


@pytest.mark.parametrize(
    "cambio",
    [
        {"variable": "inventada"},
        {"valor_nuevo": None},
        {"valor_nuevo": "NaN"},
        {"valor_nuevo": "Infinity"},
        {"valor_nuevo": 50.1},
        {"valor_nuevo": -15.1},
        {"variable": "precipitacion", "valor_nuevo": -1},
        {"variable": "precipitacion", "valor_nuevo": 301},
        {"variable": "precipitacion", "frecuencia": "H", "hora": "14:00", "valor_nuevo": 101},
        {"motivo": "   "},
        {"autor": ""},
        {"frecuencia": "X"},
        {"frecuencia": "H"},
        {"hora": "14:00"},
        {"fecha": "2025-01-14"},
        {"fecha": "2025-01-18"},
        {"estacion": "no-existe"},
    ],
)
def test_entrada_invalida_no_escribe(cliente, cambio):
    antes = list(MedicionHoraria.objects.values())
    respuesta = cliente.post(URL, entrada(**cambio), format="json")
    assert respuesta.status_code == 400, respuesta.data
    assert not CorreccionManual.objects.exists()
    assert list(MedicionHoraria.objects.values()) == antes


def test_fecha_futura_no_escribe(cliente):
    respuesta = cliente.post(
        URL, entrada(fecha=(timezone.localdate() + timedelta(days=1)).isoformat()), format="json"
    )
    assert respuesta.status_code == 400 and "fecha" in respuesta.json()


@pytest.mark.parametrize("fecha,hora", [("2025-04-05", "23:30"), ("2025-09-07", "00:30")])
def test_hora_ambigua_o_inexistente_no_se_adivina(cliente, fecha, hora):
    respuesta = cliente.post(URL, entrada(fecha=fecha, hora=hora, frecuencia="H"), format="json")
    assert respuesta.status_code == 400 and "hora" in respuesta.json()


@pytest.mark.parametrize(
    "variable,valor,frecuencia,hora",
    [
        ("tmedia", -15, "D", None),
        ("tmax", 50, "D", None),
        ("precipitacion", 300, "D", None),
        ("precipitacion", 100, "H", "14:00"),
    ],
)
def test_limites_del_catalogo_son_inclusivos(cliente, variable, valor, frecuencia, hora):
    crear(cliente, variable=variable, valor_nuevo=valor, frecuencia=frecuencia, hora=hora)
    dato = MedicionHoraria.objects.get(timestamp__date="2025-01-16")
    assert dato.valor == valor and dato.frecuencia == frecuencia and dato.origen == "manual"


@pytest.mark.parametrize("cabecera", [None, "incorrecta"])
def test_todas_las_rutas_exigen_clave(entorno, cabecera):
    cliente = APIClient(**({"HTTP_X_API_KEY": cabecera} if cabecera else {}))
    assert cliente.get(URL).status_code == 401
    assert cliente.post(URL, entrada(), format="json").status_code == 401
    assert revertir(cliente, 999).status_code == 401
    assert not CorreccionManual.objects.exists()


def test_configuracion_sin_clave_no_abre_la_api(cliente, settings):
    settings.INGESTA_API_KEY = ""
    assert cliente.get(URL).status_code == 401
    assert cliente.post(URL, entrada(), format="json").status_code == 401


def test_bitacora_filtrada_paginada_con_autoria(cliente):
    crear(cliente)
    respuesta = cliente.get(URL, {"estacion": "sc"}).json()
    assert respuesta["count"] == 1 and respuesta["results"][0]["autor"] == "Enóloga de prueba"
    assert "dato_anterior" not in respuesta["results"][0]
    assert cliente.get(URL, {"estacion": "otra"}).json()["count"] == 0


def test_rechazo_vincula_solo_la_fila_indicada(cliente, entorno):
    carga = RegistroCarga.objects.create(
        estacion=entorno.nombre,
        archivo="mala.xlsx",
        temporada=2025,
        detalle_rechazos=[
            {
                "fila": f,
                "valor_original": "fecha mala",
                "motivo": "Fecha vacía o inválida en una fila con datos",
            }
            for f in (8, 9)
        ],
    )
    correccion = crear(cliente, carga_origen=carga.pk, fila_origen=8)
    rechazadas = {f["fila"]: f for f in fallas().json()["fallas"] if f["tipo"] == "rechazado"}
    assert rechazadas[8]["corregido"] is True and rechazadas[9]["corregido"] is False
    assert correccion["carga_origen"] == carga.pk and correccion["fila_origen"] == 8
    assert revertir(cliente, correccion["id"]).status_code == 200
    assert all(not f["corregido"] for f in fallas().json()["fallas"])


def test_carga_otra_estacion_o_fila_inexistente_se_rechaza(cliente, entorno):
    carga = RegistroCarga.objects.create(
        estacion="Otra", archivo="otro.xlsx", temporada=2025, detalle_rechazos=[{"fila": 8}]
    )
    assert (
        cliente.post(URL, entrada(carga_origen=carga.pk, fila_origen=8), format="json").status_code
        == 400
    )
    carga.estacion = entorno.nombre
    carga.save()
    assert (
        cliente.post(URL, entrada(carga_origen=carga.pk, fila_origen=9), format="json").status_code
        == 400
    )
    assert cliente.post(URL, entrada(carga_origen=carga.pk), format="json").status_code == 400


def test_fallo_recalculo_conserva_auditoria_y_no_anuncia_exito(cliente, monkeypatch):
    def falla(*args, **kwargs):
        raise CommandError("Fallo interno de prueba")

    monkeypatch.setattr(correcciones, "call_command", falla)
    respuesta = cliente.post(URL, entrada(), format="json")
    assert respuesta.status_code == 503 and respuesta.json()["actualizacion"]["ok"] is False
    assert CorreccionManual.objects.count() == 1
    assert MedicionHoraria.objects.get(timestamp__date="2025-01-16").origen == "manual"
    assert "Fallo interno" not in respuesta.content.decode()


def test_reversion_no_pisa_una_medicion_modificada_por_fuera(cliente):
    correccion = crear(cliente)
    MedicionHoraria.objects.filter(timestamp__date="2025-01-16").update(valor=30, origen="excel")
    assert revertir(cliente, correccion["id"]).status_code == 409
    assert MedicionHoraria.objects.get(timestamp__date="2025-01-16").valor == 30


def test_correccion_no_desplaza_otras_frecuencias_silenciosamente(cliente, entorno):
    assert (
        cliente.post(
            URL, entrada(fecha="2025-01-15", frecuencia="H", hora="14:00"), format="json"
        ).status_code
        == 400
    )
    medir(entorno, "2025-01-16", frecuencia="H", hora=14)
    assert cliente.post(URL, entrada(), format="json").status_code == 400


def test_periodo_conserva_los_bordes_del_excel_tras_corregirlos(cliente):
    MedicionHoraria.objects.exclude(variable="temperatura_media").delete()
    primera = crear(cliente, fecha="2025-01-15")
    crear(cliente, fecha="2025-01-17")
    crear(cliente, fecha="2025-01-15", valor_nuevo=22)
    crear(cliente)
    assert CorreccionManual.objects.get(pk=primera["id"]).estado == "reemplazada"


def test_excel_correccion_y_pipeline_no_inventan_otras_mediciones(cliente, entorno, tmp_path):
    MedicionHoraria.objects.all().delete()
    ingestar(
        crear_excel(tmp_path / "datos.xlsx", [fila("2025-01-15", None), fila("2025-01-17")]),
        temporada=2025,
    )
    antes = {m.pk: (m.valor, m.origen) for m in MedicionHoraria.objects.all()}
    crear(cliente, fecha="2025-01-15")
    modificada = MedicionHoraria.objects.get(
        timestamp__date="2025-01-15", variable="temperatura_media"
    )
    assert modificada.origen == "manual" and modificada.valor == 21
    for dato in MedicionHoraria.objects.exclude(pk=modificada.pk):
        assert (dato.valor, dato.origen) == antes[dato.pk]
    assert MedicionHoraria.objects.count() == len(antes)
    assert not MedicionHoraria.objects.filter(timestamp__date="2025-01-16").exists()
    assert next(d for d in dias_json() if d["fecha"] == "2025-01-15")["tmedia"] == 21


def test_lluvia_horaria_manual_se_publica_sin_inventar_temperaturas(cliente):
    correccion = crear(
        cliente, variable="precipitacion", valor_nuevo=12.5, frecuencia="H", hora="14:00"
    )
    dia = next(d for d in dias_json() if d["fecha"] == "2025-01-16")
    assert dia["precipitacion"] == 12.5
    assert dia["tmax"] is None and dia["tmedia"] is None and dia["tmin"] is None
    assert revertir(cliente, correccion["id"]).status_code == 200
    assert not any(d["fecha"] == "2025-01-16" for d in dias_json())


def test_sin_periodo_observado_no_inventa_fechas(cliente):
    MedicionHoraria.objects.all().delete()
    respuesta = cliente.post(URL, entrada(), format="json")
    assert respuesta.status_code == 400 and "fecha" in respuesta.json()
    assert not CorreccionManual.objects.exists()


def test_hora_futura_del_mismo_dia_es_400(cliente, monkeypatch):
    momento = timezone.make_aware(datetime(2025, 1, 16, 10))
    monkeypatch.setattr(timezone, "now", lambda: momento)
    respuesta = cliente.post(URL, entrada(frecuencia="H", hora="11:00"), format="json")
    assert respuesta.status_code == 400 and "fecha" in respuesta.json()


@pytest.mark.django_db(transaction=True)
def test_dos_peticiones_concurrentes_dejan_una_sola_vigente(entorno):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import connections

    inicio = Barrier(2)

    def enviar(valor):
        try:
            inicio.wait(timeout=10)
            respuesta = APIClient(HTTP_X_API_KEY=CLAVE).post(
                URL, entrada(valor_nuevo=valor), format="json"
            )
            return respuesta.status_code, respuesta.json()
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        respuestas = list(executor.map(enviar, (21, 22)))
    assert [r[0] for r in respuestas] == [201, 201], respuestas
    assert CorreccionManual.objects.count() == 2
    vigente = CorreccionManual.objects.get(estado="vigente")
    assert vigente.anterior.estado == "reemplazada"
    assert MedicionHoraria.objects.get(timestamp__date="2025-01-16").valor == vigente.valor_nuevo
    assert (
        next(d for d in dias_json() if d["fecha"] == "2025-01-16")["tmedia"] == vigente.valor_nuevo
    )


def test_varias_variables_del_hueco_conservan_su_falla_hasta_revertir_la_ultima(cliente):
    primera = crear(cliente)
    segunda = crear(cliente, variable="tmax", valor_nuevo=25)
    assert revertir(cliente, primera["id"]).status_code == 200
    huecos = [f for f in fallas().json()["fallas"] if f["tipo"] == "sin_registro"]
    assert len(huecos) == 1 and huecos[0]["corregido"] is True
    assert huecos[0]["correcciones"] == [segunda["id"]]
    assert revertir(cliente, segunda["id"]).status_code == 200
    assert (
        next(f for f in fallas().json()["fallas"] if f["tipo"] == "sin_registro")["corregido"]
        is False
    )


def test_rechazo_sin_fecha_se_marca_en_ambas_temporadas_donde_aparece(cliente, entorno):
    carga = RegistroCarga.objects.create(
        estacion=entorno.nombre,
        archivo="mala.xlsx",
        temporada=2025,
        detalle_rechazos=[{"fila": 8, "valor_original": "fecha mala", "motivo": "Fecha inválida"}],
    )
    crear(cliente, carga_origen=carga.pk, fila_origen=8)
    for temporada in ("2024-2025", "2025-2026"):
        rechazo = next(
            f for f in fallas(temporada=temporada).json()["fallas"] if f["tipo"] == "rechazado"
        )
        assert rechazo["corregido"] is True
