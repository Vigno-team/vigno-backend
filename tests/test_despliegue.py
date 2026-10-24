import json

import pytest
from rest_framework.test import APIClient

from deploy.tareas import intervalo_segundos, saludable


def test_api_entrega_archivo_actual_y_no_cachea(settings, tmp_path):
    settings.DATOS_DIR = tmp_path
    ruta = tmp_path / "vigno-datos-reales.json"
    cliente = APIClient()
    for valor in (1, 2):
        ruta.write_text(json.dumps({"estaciones": [], "version": valor}))
        respuesta = cliente.get("/api/v1/datos")
        assert respuesta.status_code == 200
        assert respuesta.json()["version"] == valor
        assert respuesta["Cache-Control"] == "no-store"
    assert cliente.post("/api/v1/datos", {}).status_code == 405


@pytest.mark.parametrize("contenido", [None, "incompleto{", "[]"])
def test_api_datos_ausentes_o_invalidos_es_503(settings, tmp_path, contenido):
    settings.DATOS_DIR = tmp_path
    if contenido is not None:
        (tmp_path / "vigno-datos-reales.json").write_text(contenido)
    respuesta = APIClient().get("/api/v1/datos")
    assert respuesta.status_code == 503
    assert respuesta["Retry-After"] == "30"
    assert str(tmp_path) not in respuesta.content.decode()


@pytest.mark.parametrize("valor", ["0", "-1", "nan", "inf", "texto"])
def test_programador_rechaza_intervalos_invalidos(valor):
    with pytest.raises(ValueError):
        intervalo_segundos(valor)


def test_programador_estado_distingue_exito_fallo_y_resultado_viejo(tmp_path):
    ruta = tmp_path / "estado.json"
    assert intervalo_segundos("360") == 21600
    assert not saludable(ruta, 60, ahora=500)
    ruta.write_text(json.dumps({"codigo": 0, "termino": 400}))
    assert saludable(ruta, 60, ahora=500)
    assert not saludable(ruta, 60, ahora=900)
    ruta.write_text(json.dumps({"codigo": 1, "termino": 400}))
    assert not saludable(ruta, 60, ahora=500)


def test_programador_corre_al_inicio_y_reintenta_sin_solapar(monkeypatch, tmp_path):
    from deploy import tareas

    eventos = []

    class Espera:
        def is_set(self):
            return len([e for e in eventos if e == "fin"]) == 2

        def wait(self, segundos):
            eventos.append(("espera", segundos))

    class Proceso:
        def __init__(self, argumentos):
            assert argumentos[1:] == ["manage.py", "actualizar_todo"]
            eventos.append("inicio")

        def wait(self):
            eventos.append("fin")
            return 1 if eventos.count("fin") == 1 else 0

    monkeypatch.setattr(tareas.threading, "Event", Espera)
    monkeypatch.setattr(tareas.subprocess, "Popen", Proceso)
    monkeypatch.setattr(tareas.signal, "signal", lambda *args: None)
    monkeypatch.setattr(tareas, "ESTADO", tmp_path / "estado.json")
    monkeypatch.setattr(tareas.sys, "argv", ["tareas.py"])
    monkeypatch.setenv("INTERVALO_ACTUALIZACION_MIN", "1")
    assert tareas.main() == 0
    assert eventos == ["inicio", "fin", ("espera", 60), "inicio", "fin", ("espera", 60)]
    assert json.loads(tareas.ESTADO.read_text())["codigo"] == 0
