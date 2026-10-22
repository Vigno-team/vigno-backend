"""E1C-129: actualizar_todo con los pasos simulados, sin red."""

import json
import os
import threading
import time
from datetime import date, datetime, timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.utils import timezone

from apps.clima.archivos import escribir_json_atomico
from apps.clima.management.commands import actualizar_todo
from apps.clima.models import CapaSatelital, Estacion

pytestmark = pytest.mark.django_db

PASOS = [
    "generar_resumenes",
    "calcular_indices",
    "clasificar_temporadas",
    "actualizar_mapa_calor",
    "entrenar_cosecha",
    "exportar_prediccion_ficticia",
    "exportar_json",
]


class Registro(list):
    fallar: dict


@pytest.fixture
def entorno(settings, tmp_path, monkeypatch):
    """Proyecto falso en tmp_path: un predio con contorno, otro sin él, y cosechas.csv."""
    settings.BASE_DIR = tmp_path
    settings.DATOS_DIR = tmp_path / "datos"
    settings.CDSE_CLIENT_ID = "id"
    settings.CDSE_CLIENT_SECRET = "secreto"

    contorno = {
        "type": "Polygon",
        "coordinates": [[[-71.5, -35.5], [-71.4, -35.5], [-71.4, -35.4], [-71.5, -35.5]]],
    }
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "areas_mapa.json").write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [
                    {"properties": {"codigo": "con-contorno"}, "geometry": contorno},
                    {"properties": {"codigo": "sin-contorno"}, "geometry": None},
                ],
            }
        ),
        encoding="utf-8",
    )
    Estacion.objects.create(nombre="Con contorno", codigo="con-contorno")
    Estacion.objects.create(nombre="Sin contorno", codigo="sin-contorno")

    (tmp_path / "data" / "ficticio").mkdir(parents=True)
    (tmp_path / "data" / "ficticio" / "cosechas.csv").write_text("anio\n1941\n")
    monkeypatch.setattr(actualizar_todo, "hay_sklearn", lambda: True)
    return tmp_path


@pytest.fixture
def llamadas(monkeypatch):
    """Reemplaza call_command de los pasos; `fallar` define qué pasos lanzan error."""
    registro = Registro()
    registro.fallar = {}

    def falso(nombre, *args, **kwargs):
        registro.append((nombre, args, kwargs))
        if nombre in registro.fallar:
            raise registro.fallar[nombre]

    monkeypatch.setattr(actualizar_todo, "call_command", falso)
    return registro


def correr(*args):
    call_command("actualizar_todo", *args)


def leer_actualizacion(entorno):
    return json.loads((entorno / "datos" / "actualizacion.json").read_text(encoding="utf-8"))


def nombres(llamadas):
    return [nombre for nombre, _, _ in llamadas]


def test_corre_los_pasos_en_orden(entorno, llamadas):
    correr()

    assert nombres(llamadas) == PASOS
    _, _, kwargs = llamadas[3]
    assert kwargs == {"estacion": "con-contorno", "capa": "ndvi"}
    _, args, _ = llamadas[-1]
    assert args == (
        "--salida",
        str(entorno / "datos" / "vigno-datos-reales.json"),
        "--sobrescribir",
    )
    assert [p["paso"] for p in leer_actualizacion(entorno)["pasos"]] == PASOS


def test_fallo_del_satelite_no_corta_el_resto(entorno, llamadas):
    llamadas.fallar["actualizar_mapa_calor"] = CommandError("Copernicus no responde")

    correr()  # no lanza: el satélite no es crítico

    assert nombres(llamadas) == PASOS
    estado = leer_actualizacion(entorno)
    assert estado["ok"] is True
    mapa = next(p for p in estado["pasos"] if p["paso"] == "actualizar_mapa_calor")
    assert mapa["ok"] is False
    assert "Copernicus no responde" in mapa["detalle"]


def test_fallo_critico_sigue_y_termina_con_error(entorno, llamadas):
    llamadas.fallar["calcular_indices"] = ValueError("sin datos")

    with pytest.raises(CommandError, match="calcular_indices"):
        correr()

    assert nombres(llamadas) == PASOS
    estado = leer_actualizacion(entorno)
    assert estado["ok"] is False
    assert [p["ok"] for p in estado["pasos"]] == [True, False, True, True, True, True, True]


def test_formato_de_actualizacion_json(entorno, llamadas):
    correr()

    estado = leer_actualizacion(entorno)
    assert list(estado) == ["generado", "ok", "pasos"]
    generado = datetime.fromisoformat(estado["generado"])
    assert generado.utcoffset() == timezone.localtime().utcoffset()
    assert estado["generado"] == generado.isoformat(timespec="seconds")
    for paso in estado["pasos"]:
        assert list(paso) == ["paso", "ok", "segundos", "detalle"]
        assert isinstance(paso["ok"], bool)
        assert isinstance(paso["segundos"], float)
        assert isinstance(paso["detalle"], str)


def test_sin_satelite(entorno, llamadas):
    correr("--sin-satelite")

    assert "actualizar_mapa_calor" not in nombres(llamadas)
    mapa = leer_actualizacion(entorno)["pasos"][3]
    assert mapa["ok"] is True
    assert mapa["detalle"] == "omitido: --sin-satelite"


def test_sin_credenciales_no_pide_capas(entorno, llamadas, settings):
    settings.CDSE_CLIENT_SECRET = ""

    correr()

    assert "actualizar_mapa_calor" not in nombres(llamadas)
    assert leer_actualizacion(entorno)["pasos"][3]["detalle"].startswith("omitido")


def crear_capa(fecha):
    CapaSatelital.objects.create(
        estacion=Estacion.objects.get(codigo="con-contorno"),
        capa="ndvi",
        fecha_imagen=fecha,
        limites=[0, 0, 1, 1],
        crs="EPSG:32719",
        ancho=1,
        alto=1,
        resolucion_m=10,
        valores=[[0.5]],
        porcentaje_validos=100,
        version="test",
    )


def test_capa_reciente_no_se_vuelve_a_pedir(entorno, llamadas):
    crear_capa(timezone.localdate() - timedelta(days=2))

    correr()

    assert "actualizar_mapa_calor" not in nombres(llamadas)
    assert "vigentes: con-contorno" in leer_actualizacion(entorno)["pasos"][3]["detalle"]


def test_capa_vieja_se_actualiza(entorno, llamadas):
    crear_capa(timezone.localdate() - timedelta(days=6))
    crear_capa(date(2020, 1, 1))

    correr()

    assert "actualizar_mapa_calor" in nombres(llamadas)


def test_forzar_satelite(entorno, llamadas):
    crear_capa(timezone.localdate())

    correr("--forzar-satelite")

    assert "actualizar_mapa_calor" in nombres(llamadas)


def test_no_reentrena_si_la_evaluacion_es_mas_nueva(entorno, llamadas):
    csv = entorno / "data" / "ficticio" / "cosechas.csv"
    evaluacion = csv.with_name("prediccion_cosecha_california.json")
    evaluacion.write_text("{}")
    os.utime(csv, (time.time() - 60, time.time() - 60))

    correr()

    assert "entrenar_cosecha" not in nombres(llamadas)
    assert "exportar_prediccion_ficticia" in nombres(llamadas)


def test_reentrena_si_el_csv_es_mas_nuevo(entorno, llamadas):
    csv = entorno / "data" / "ficticio" / "cosechas.csv"
    evaluacion = csv.with_name("prediccion_cosecha_california.json")
    evaluacion.write_text("{}")
    os.utime(evaluacion, (time.time() - 60, time.time() - 60))

    correr()

    assert "entrenar_cosecha" in nombres(llamadas)


def test_sin_sklearn_omite_entrenar_pero_exporta_la_evaluacion(entorno, llamadas, monkeypatch):
    monkeypatch.setattr(actualizar_todo, "hay_sklearn", lambda: False)
    (entorno / "data" / "ficticio" / "cosechas.csv").unlink()
    (entorno / "data" / "ficticio" / "prediccion_cosecha_california.json").write_text("{}")

    correr()

    assert "entrenar_cosecha" not in nombres(llamadas)
    assert "exportar_prediccion_ficticia" in nombres(llamadas)
    assert leer_actualizacion(entorno)["ok"] is True


def test_sin_evaluacion_omite_exportar_prediccion(entorno, llamadas, monkeypatch):
    monkeypatch.setattr(actualizar_todo, "hay_sklearn", lambda: False)

    correr()

    assert "exportar_prediccion_ficticia" not in nombres(llamadas)
    paso = leer_actualizacion(entorno)["pasos"][5]
    assert paso["ok"] is True
    assert paso["detalle"].startswith("omitido: no existe")


def test_sin_csv_omite_clasificar_temporadas_y_termina_bien(entorno, llamadas):
    (entorno / "data" / "ficticio" / "cosechas.csv").unlink()

    correr()

    assert "clasificar_temporadas" not in nombres(llamadas)
    estado = leer_actualizacion(entorno)
    assert estado["ok"] is True
    assert estado["pasos"][2]["detalle"].startswith("omitido")


def test_con_csv_un_fallo_de_clasificar_temporadas_es_critico(entorno, llamadas):
    llamadas.fallar["clasificar_temporadas"] = CommandError("etiqueta desconocida")

    with pytest.raises(CommandError, match="clasificar_temporadas"):
        correr()

    assert leer_actualizacion(entorno)["ok"] is False


def test_escritura_atomica_reemplaza_el_archivo(tmp_path):
    ruta = tmp_path / "datos.json"
    ruta.write_text('{"viejo": true}', encoding="utf-8")

    escribir_json_atomico(ruta, {"nuevo": "ñ"})

    assert json.loads(ruta.read_text(encoding="utf-8")) == {"nuevo": "ñ"}
    assert list(tmp_path.iterdir()) == [ruta]


def test_escritura_atomica_no_deja_el_archivo_a_medias(tmp_path, monkeypatch):
    ruta = tmp_path / "datos.json"
    ruta.write_text('{"viejo": true}', encoding="utf-8")
    temporales = []

    def replace_que_falla(origen, destino):
        temporales.append(origen)
        assert os.path.dirname(origen) == str(tmp_path)  # misma carpeta: os.replace es atómico
        raise OSError("disco lleno")

    monkeypatch.setattr(os, "replace", replace_que_falla)

    with pytest.raises(OSError):
        escribir_json_atomico(ruta, {"nuevo": True})

    assert temporales
    assert json.loads(ruta.read_text(encoding="utf-8")) == {"viejo": True}
    assert list(tmp_path.iterdir()) == [ruta]


def test_escritura_atomica_valida_antes_de_tocar_el_disco(tmp_path):
    ruta = tmp_path / "datos.json"
    ruta.write_text('{"viejo": true}', encoding="utf-8")

    with pytest.raises(ValueError):
        escribir_json_atomico(ruta, {"nan": float("nan")})

    assert json.loads(ruta.read_text(encoding="utf-8")) == {"viejo": True}
    assert list(tmp_path.iterdir()) == [ruta]


def test_exportar_json_escribe_de_forma_atomica(tmp_path, monkeypatch):
    from apps.clima.management.commands import exportar_json

    usadas = []
    monkeypatch.setattr(
        exportar_json, "escribir_json_atomico", lambda ruta, datos: usadas.append(ruta)
    )

    call_command("exportar_json", "--salida", str(tmp_path / "datos.json"))

    assert usadas == [tmp_path / "datos.json"]


@pytest.mark.django_db(transaction=True)
def test_una_segunda_corrida_espera_a_la_primera():
    entro = threading.Event()

    def segunda():
        try:
            with actualizar_todo.candado():
                entro.set()
        finally:
            connection.close()

    with actualizar_todo.candado():
        hilo = threading.Thread(target=segunda)
        hilo.start()
        assert not entro.wait(0.5)  # sigue esperando mientras la primera tiene el candado
    hilo.join(timeout=5)
    assert entro.is_set()
