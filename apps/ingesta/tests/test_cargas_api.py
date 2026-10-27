"""E1C-66: carga de Excel por API, validación previa y la regla de la celda vacía."""

import json
from pathlib import Path

import openpyxl
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.clima.models import Estacion, MedicionHoraria
from apps.clima.tests.test_ingestar_excel import crear_excel, fila
from apps.ingesta import carga, views
from apps.ingesta.models import RegistroCarga

pytestmark = pytest.mark.django_db

URL = "/api/v1/cargas"
CLAVE = "clave-de-prueba"
ESTACION = "cp-san-clemente-01"


@pytest.fixture(autouse=True)
def entorno(settings, tmp_path):
    settings.INGESTA_API_KEY = CLAVE
    settings.DATOS_DIR = tmp_path / "datos"


@pytest.fixture(autouse=True)
def recalculos(monkeypatch, settings):
    """Reemplaza actualizar_todo: anota la llamada y deja un actualizacion.json."""
    llamadas = []

    def falso(nombre, *args, **kwargs):
        llamadas.append((nombre, args))
        settings.DATOS_DIR.mkdir(parents=True, exist_ok=True)
        (settings.DATOS_DIR / "actualizacion.json").write_text(
            json.dumps({"generado": "2026-10-26T21:00:00-03:00", "ok": True, "pasos": []})
        )

    monkeypatch.setattr(views, "call_command", falso)
    return llamadas


@pytest.fixture
def api():
    return APIClient(HTTP_X_API_KEY=CLAVE)


def subir(cliente, ruta, query="", **datos):
    ruta = Path(ruta)
    archivo = SimpleUploadedFile(ruta.name, ruta.read_bytes())
    return cliente.post(
        URL + query, {"archivo": archivo, "estacion": ESTACION, **datos}, format="multipart"
    )


def tres_dias(tmp_path, nombre="san_clemente_2025.xlsx"):
    return crear_excel(
        tmp_path / nombre, [fila("2025-01-10"), fila("2025-01-11"), fila("2025-01-12")]
    )


def estado_de_la_base():
    return (
        RegistroCarga.objects.count(),
        list(MedicionHoraria.objects.order_by("pk").values_list("pk", "valor")),
    )


def excel_mensual(ruta, encabezado_superior, encabezado_inferior, filas):
    libro = openpyxl.Workbook()
    hoja = libro.active
    hoja.title = "mensual"
    for i in range(4):
        hoja.append([f"Basura {i}"])
    hoja.append(encabezado_superior)
    hoja.append(encabezado_inferior)
    hoja.append([])
    for f in filas:
        hoja.append(f)
    libro.save(ruta)
    return ruta


# --- carga válida ---------------------------------------------------------------------------


def test_carga_valida_guarda_recalcula_y_responde_el_resumen(api, tmp_path, recalculos, settings):
    respuesta = subir(api, tres_dias(tmp_path))

    assert respuesta.status_code == 201, respuesta.json()
    datos = respuesta.json()
    assert datos["valido"] is True
    assert datos["estacion"] == "San Clemente"
    assert datos["estacion_id"] == ESTACION
    assert datos["temporada"] == 2025
    assert datos["origen_temporada"] == "nombre del archivo"
    assert (datos["fecha_desde"], datos["fecha_hasta"]) == ("2025-01-10", "2025-01-12")
    assert datos["conteos"] == {
        "insertados": 21,
        "actualizados": 0,
        "sin_cambio": 0,
        "omitidos": 0,
        "rechazados": 0,
    }
    assert datos["recalculo"]["ok"] is True
    assert recalculos == [("actualizar_todo", ("--sin-satelite",))]

    registro = RegistroCarga.objects.get()
    assert registro.archivo == "san_clemente_2025.xlsx"
    assert (settings.DATOS_DIR / "cargas" / f"{registro.hash_archivo}.xlsx").is_file()


def test_el_mismo_archivo_dos_veces_es_una_sola_carga(api, tmp_path, recalculos):
    ruta = tres_dias(tmp_path)
    primera = subir(api, ruta)
    antes = estado_de_la_base()

    segunda = subir(api, ruta)

    assert segunda.status_code == 200
    assert segunda.json()["repetida"] is True
    assert segunda.json()["id"] == primera.json()["id"]
    assert estado_de_la_base() == antes
    assert len(recalculos) == 1


def test_estacion_nueva_sin_mapeo_propio_carga_con_formato_estandar(api, tmp_path):
    # Las estaciones nuevas se crean con POST /api/v1/estaciones (E1C-68), sin mapeo propio.
    Estacion.objects.create(nombre="Villa Nueva", codigo="villa-nueva")

    respuesta = subir(api, tres_dias(tmp_path), estacion="villa-nueva")

    assert respuesta.status_code == 201, respuesta.json()
    assert respuesta.json()["estacion"] == "Villa Nueva"
    assert respuesta.json()["formato"] == "B_2023_2026"
    assert MedicionHoraria.objects.filter(estacion__codigo="villa-nueva").count() == 21


def test_la_estacion_tambien_se_puede_indicar_por_nombre(api, tmp_path):
    respuesta = subir(api, tres_dias(tmp_path), estacion="san clemente")

    assert respuesta.status_code == 201
    assert respuesta.json()["estacion"] == "San Clemente"


# --- rechazos antes de procesar: 400 y 401 ----------------------------------------------------


def test_extension_invalida_da_400(api, tmp_path, recalculos):
    ruta = tmp_path / "datos.csv"
    ruta.write_text("FECHA;TEMPERATURA\n")

    respuesta = subir(api, ruta)

    assert respuesta.status_code == 400
    assert respuesta.json()["valido"] is False
    assert ".xls o .xlsx" in respuesta.json()["errores"][0]
    assert recalculos == []


def test_archivo_demasiado_grande_da_400(api, tmp_path, monkeypatch):
    umbrales = {**carga.cargar_umbrales(), "tamano_maximo_mb": 0.001}
    monkeypatch.setattr(carga, "cargar_umbrales", lambda: umbrales)

    respuesta = subir(api, tres_dias(tmp_path))

    assert respuesta.status_code == 400
    assert "el máximo es 0.001 MB" in respuesta.json()["errores"][0]


def test_post_sin_clave_o_con_clave_incorrecta_da_401(tmp_path, recalculos):
    ruta = tres_dias(tmp_path)

    assert subir(APIClient(), ruta).status_code == 401
    assert subir(APIClient(HTTP_X_API_KEY="otra"), ruta).status_code == 401
    assert RegistroCarga.objects.count() == 0
    assert recalculos == []


@pytest.mark.xfail(
    strict=True,
    reason="Los GET pasan a pedir la clave con ApiKeyPrivadaAuthentication del PR #52 (E1C-131). "
    "Cuando entre: cambiar las vistas y quitar este xfail.",
)
def test_get_de_cargas_sin_clave_da_401(api, tmp_path):
    creada = subir(api, tres_dias(tmp_path)).json()

    assert APIClient().get(URL).status_code == 401
    assert APIClient().get(f"{URL}/{creada['id']}").status_code == 401


def test_estacion_no_registrada_da_400(api, tmp_path):
    respuesta = subir(api, tres_dias(tmp_path), estacion="No Existe")

    assert respuesta.status_code == 400
    assert respuesta.json()["errores"] == ["La estación No Existe no existe; créala primero"]


# --- rechazos con 422: la base no cambia ------------------------------------------------------


def rechaza_sin_tocar_la_base(api, ruta, recalculos):
    antes = estado_de_la_base()
    respuesta = subir(api, ruta)
    assert respuesta.status_code == 422, respuesta.json()
    assert respuesta.json()["valido"] is False
    assert estado_de_la_base() == antes
    assert recalculos == []
    return respuesta.json()["errores"]


def test_archivo_danado_da_422(api, tmp_path, recalculos):
    ruta = tmp_path / "danado_2025.xlsx"
    ruta.write_bytes(b"esto no es un excel")

    errores = rechaza_sin_tocar_la_base(api, ruta, recalculos)

    assert "dañado, protegido con contraseña" in errores[0]


def test_sin_hoja_mensual_da_422(api, tmp_path, recalculos):
    ruta = tmp_path / "otra_hoja_2025.xlsx"
    libro = openpyxl.Workbook()
    libro.active.title = "resumen"
    libro.save(ruta)

    errores = rechaza_sin_tocar_la_base(api, ruta, recalculos)

    assert errores == ["El archivo no tiene la hoja 'mensual'. Hojas encontradas: resumen."]


def test_columnas_faltantes_nombra_las_columnas(api, tmp_path, recalculos):
    ruta = excel_mensual(
        tmp_path / "incompleto_2025.xlsx",
        ["FECHA", "TEMPERATURA", "TEMPERATURA", "PP"],
        [None, "Media diaria", "Máxima", "(mm)"],
        [["2025-01-10", 15.0, 20.0, 0.0]],
    )

    errores = rechaza_sin_tocar_la_base(api, ruta, recalculos)

    assert len(errores) == 1
    assert "formato más parecido (B_2023_2026)" in errores[0]
    for columna in ("TEMPERATURA / Mínima", "HUMEDAD RELATIVA / H.R. Media (%)"):
        assert columna in errores[0]


def test_temperaturas_vacias_sobre_el_umbral_dan_422(api, tmp_path, recalculos):
    sin_temperaturas = [None, None, None, 50.0, 800.0, 5.0, 100, 0.0]
    ruta = crear_excel(
        tmp_path / "sin_temperaturas_2025.xlsx",
        [["2025-01-10", *sin_temperaturas], ["2025-01-11", *sin_temperaturas], fila("2025-01-12")],
    )

    errores = rechaza_sin_tocar_la_base(api, ruta, recalculos)

    assert len(errores) == 3
    assert errores[0] == (
        "La columna TEMPERATURA / Máxima viene vacía o no numérica en el 67 % de las filas "
        "(2 de 3); el máximo es 50 %."
    )


def test_mas_de_20_por_ciento_de_fechas_invalidas_da_422(api, tmp_path, recalculos):
    ruta = crear_excel(
        tmp_path / "fechas_malas_2025.xlsx",
        [fila("2025-01-10"), fila("no es fecha"), fila("2025-01-12"), fila("tampoco")],
    )

    errores = rechaza_sin_tocar_la_base(api, ruta, recalculos)

    assert errores == ["El 50 % de las fechas son inválidas (2 de 4 filas); el máximo es 20 %."]


def test_sin_filas_validas_da_422(api, tmp_path, recalculos):
    ruta = crear_excel(tmp_path / "vacio_2025.xlsx", [])

    errores = rechaza_sin_tocar_la_base(api, ruta, recalculos)

    assert errores == ["No quedó ninguna fila válida para cargar."]


# --- solo validar -----------------------------------------------------------------------------


def test_solo_validar_no_escribe_en_la_base(api, tmp_path, recalculos, settings):
    antes = estado_de_la_base()

    respuesta = subir(api, tres_dias(tmp_path), query="?solo_validar=1")

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["solo_validar"] is True
    assert datos["temporada"] == 2025
    assert (datos["fecha_desde"], datos["fecha_hasta"]) == ("2025-01-10", "2025-01-12")
    assert datos["filas"]["aceptadas"] == 3
    assert datos["conteos"]["insertados"] == 21
    assert estado_de_la_base() == antes
    assert not (settings.DATOS_DIR / "cargas").exists()
    assert recalculos == []


def test_solo_validar_tambien_rechaza_con_422(api, tmp_path, recalculos):
    ruta = tmp_path / "danado_2025.xlsx"
    ruta.write_bytes(b"esto no es un excel")

    assert subir(api, ruta, query="?solo_validar=1").status_code == 422


# --- una celda vacía no borra un dato existente -----------------------------------------------


def cinco_dias(tmp_path):
    return crear_excel(
        tmp_path / "san_clemente_2025.xlsx", [fila(f"2025-01-1{d}") for d in range(5)]
    )


def corregir_dos_celdas(tmp_path):
    """Recarga con la media del 10 vacía, la del 11 con texto y la del 12 corregida."""
    return crear_excel(
        tmp_path / "san_clemente_2025_v2.xlsx",
        [
            fila("2025-01-10", None),
            fila("2025-01-11", "s/d"),
            fila("2025-01-12", 16.0),
            fila("2025-01-13"),
            fila("2025-01-14"),
        ],
    )


def test_celda_vacia_no_borra_un_dato_ya_cargado(api, tmp_path):
    subir(api, cinco_dias(tmp_path))

    respuesta = subir(api, corregir_dos_celdas(tmp_path))

    assert respuesta.status_code == 201, respuesta.json()
    medias = dict(
        MedicionHoraria.objects.filter(variable="temperatura_media").values_list(
            "timestamp__day", "valor"
        )
    )
    assert medias == {10: 15.0, 11: 15.0, 12: 16.0, 13: 15.0, 14: 15.0}
    datos = respuesta.json()
    assert datos["conteos"]["sin_cambio"] == 34
    assert datos["conteos"]["actualizados"] == 1
    assert datos["filas"]["rechazadas"] == 0
    assert datos["rechazos"] == []
    esperadas = [
        {"fila": 8, "fecha": "2025-01-10", "variable": "temperatura_media"},
        {"fila": 9, "fecha": "2025-01-11", "variable": "temperatura_media"},
    ]
    aviso = "Celda vacía: se conservó el valor anterior"
    assert datos["celdas_vacias_conservadas"] == [{**c, "aviso": aviso} for c in esperadas]
    assert RegistroCarga.objects.latest("pk").celdas_vacias_conservadas == esperadas
    detalle = api.get(f"{URL}/{datos['id']}").json()
    assert detalle["celdas_vacias_conservadas"] == datos["celdas_vacias_conservadas"]


def test_solo_validar_muestra_las_celdas_que_se_conservarian(api, tmp_path):
    subir(api, cinco_dias(tmp_path))

    datos = subir(api, corregir_dos_celdas(tmp_path), query="?solo_validar=1").json()

    assert [c["fecha"] for c in datos["celdas_vacias_conservadas"]] == ["2025-01-10", "2025-01-11"]
    assert "Celda vacía: se conservó el valor anterior (2 celdas)." in datos["advertencias"]


def test_la_celda_conservada_no_es_una_falla(api, tmp_path):
    subir(api, cinco_dias(tmp_path))
    subir(api, corregir_dos_celdas(tmp_path))

    reporte = (
        APIClient()
        .get("/api/v1/calidad/fallas", {"estacion": ESTACION, "temporada": "2024-2025"})
        .json()
    )

    assert reporte["fallas"] == []


# --- historial ----------------------------------------------------------------------------------


def test_historial_y_detalle_de_cargas(api, tmp_path):
    ruta = crear_excel(
        tmp_path / "san_clemente_2025.xlsx",
        [fila(f"2025-01-1{d}") for d in range(5)] + [fila("no es fecha")],
    )
    creada = subir(api, ruta).json()

    lista = api.get(URL).json()
    detalle = api.get(f"{URL}/{creada['id']}").json()

    assert [c["id"] for c in lista] == [creada["id"]]
    assert lista[0]["estado"] == "OK"
    assert lista[0]["filas"] == {
        "leidas": 6,
        "aceptadas": 5,
        "rechazadas": 1,
        "vacias_ignoradas": 0,
    }
    assert detalle["rechazos"] == [
        {"fila": 13, "valor_original": "no es fecha", "motivo": carga.MOTIVO_FECHA_INVALIDA}
    ]
    assert api.get(f"{URL}/999999").status_code == 404


def test_el_recalculo_real_corre_dentro_del_candado_de_la_carga(
    api, tmp_path, monkeypatch, settings
):
    """La carga y actualizar_todo usan el mismo pg_advisory_lock: no deben bloquearse."""
    from django.core.management import call_command

    from apps.clima.management.commands import actualizar_todo

    monkeypatch.setattr(views, "call_command", call_command)
    monkeypatch.setattr(actualizar_todo.Command, "correr_pasos", lambda self, options: [])

    respuesta = subir(api, tres_dias(tmp_path))

    assert respuesta.status_code == 201
    assert respuesta.json()["recalculo"]["ok"] is True
    assert (settings.DATOS_DIR / "actualizacion.json").is_file()
