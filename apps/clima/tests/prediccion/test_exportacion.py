import copy
import json
from datetime import UTC, datetime

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError


@pytest.fixture
def evaluacion():
    """Valores sintéticos solo para probar la transformación, no para la demo."""
    return {
        "datos_ficticios": True,
        "fuente": "Bai et al. (2022), Scientific Data 9:271",
        "dataset_url": "https://doi.org/10.6084/m9.figshare.19807777.v1",
        "version_modelo": "version-de-prueba",
        "features": ["GST", "Winkler", "Huglin", "region", "color"],
        "importancias_random_forest": {
            "GST": 0.1,
            "Winkler": 0.3,
            "Huglin": 0.2,
            "region": 0.3,
            "color": 0.1,
        },
        "regresion_lineal": {"intercepto_dias": 100, "coeficientes": {"GST": 0.8}},
        "metricas": {
            "random_forest": {"mae_dias": 14.1, "rmse_dias": 17.2, "n": 1},
            "promedio_regional": {"mae_dias": 12.3, "rmse_dias": 16.4, "n": 1},
        },
        "comparacion_base": {"rf_mejora_mae": False, "rf_mejora_rmse": False},
        "validacion": {"anios_entrenamiento": [1939, 1940], "anios_prueba": [1941]},
        "predicciones": [
            {
                "fuente": "Amerine & Winkler",
                "region": "II",
                "anio": 1941,
                "cultivar": "Merlot",
                "color": "Red",
                "doy_real": 260,
                "doy_estimado": 262,
                "diferencia_dias": 2,
                "fecha_real": "1941-09-17",
                "prediccion": {
                    "centro": "1941-09-19",
                    "desde": "1941-09-15",
                    "hasta": "1941-09-24",
                },
            }
        ],
    }


@pytest.fixture
def carpeta(tmp_path, settings):
    settings.BASE_DIR = tmp_path
    destino = tmp_path / "data" / "ficticio"
    destino.mkdir(parents=True)
    return destino


def escribir(carpeta, evaluacion):
    (carpeta / "prediccion_cosecha_california.json").write_text(
        json.dumps(evaluacion), encoding="utf-8"
    )


def test_exporta_valores_de_entrada_y_fechas_originales(carpeta, evaluacion, monkeypatch):
    instante = datetime(2026, 10, 20, 12, 34, tzinfo=UTC)
    monkeypatch.setattr(
        "apps.clima.management.commands.exportar_prediccion_ficticia.timezone.now",
        lambda: instante,
    )
    escribir(carpeta, evaluacion)
    original = (carpeta / "prediccion_cosecha_california.json").read_bytes()
    call_command("exportar_prediccion_ficticia")
    contenido = (carpeta / "prediccion_ficticia.json").read_bytes()
    assert not contenido.startswith(b"\xef\xbb\xbf")
    salida = json.loads(contenido.decode("utf-8"))
    assert salida["generado"] == instante.isoformat()
    assert salida["datos_ficticios"] is True
    assert salida["fuente"]["cita"] == evaluacion["fuente"]
    assert salida["fuente"]["url"] == evaluacion["dataset_url"]
    for destino, origen in (
        ("version", "version_modelo"),
        ("variables", "features"),
        ("importancias", "importancias_random_forest"),
        ("regresion_lineal", "regresion_lineal"),
        ("metricas", "metricas"),
        ("comparacion_base", "comparacion_base"),
        ("validacion", "validacion"),
    ):
        assert salida["modelo"][destino] == evaluacion[origen]
    assert salida["predicciones"] == evaluacion["predicciones"]
    assert not {"temporadas", "correlaciones", "calidad"}.intersection(salida)
    assert not (carpeta.parent / "cliente").exists()
    assert (carpeta / "prediccion_cosecha_california.json").read_bytes() == original


def test_cambios_del_entrenamiento_se_reflejan_sin_numeros_fijos(carpeta, evaluacion):
    escribir(carpeta, evaluacion)
    call_command("exportar_prediccion_ficticia")
    anterior = json.loads((carpeta / "prediccion_ficticia.json").read_text())
    nuevo = copy.deepcopy(evaluacion)
    nuevo["metricas"]["random_forest"]["mae_dias"] = 8.7654
    nuevo["importancias_random_forest"]["GST"] = 0.15
    nuevo["predicciones"][0]["cultivar"] = "Otro cultivar de prueba"
    nuevo["comparacion_base"]["rf_mejora_mae"] = True
    escribir(carpeta, nuevo)
    call_command("exportar_prediccion_ficticia")
    actual = json.loads((carpeta / "prediccion_ficticia.json").read_text())
    assert actual["modelo"]["metricas"] == nuevo["metricas"]
    assert actual["modelo"]["importancias"] == nuevo["importancias_random_forest"]
    assert actual["predicciones"] == nuevo["predicciones"]
    assert actual["modelo"]["comparacion_base"] == nuevo["comparacion_base"]
    assert actual["modelo"]["metricas"] != anterior["modelo"]["metricas"]


def test_sin_entrenamiento_pide_ejecutar_comando(carpeta):
    with pytest.raises(CommandError, match="^Corre primero: python manage.py entrenar_cosecha$"):
        call_command("exportar_prediccion_ficticia")
    assert not (carpeta / "prediccion_ficticia.json").exists()


@pytest.mark.parametrize("contenido", ["", "{", "\ufeff{}", '{"metricas": NaN}', "[]"])
def test_entrada_invalida_no_escribe_salida(carpeta, contenido):
    (carpeta / "prediccion_cosecha_california.json").write_text(contenido, encoding="utf-8")
    with pytest.raises(CommandError):
        call_command("exportar_prediccion_ficticia")
    assert not (carpeta / "prediccion_ficticia.json").exists()


@pytest.mark.parametrize("campo", ["metricas", "features", "predicciones", "version_modelo"])
def test_faltan_campos_no_se_inventan(carpeta, evaluacion, campo):
    del evaluacion[campo]
    escribir(carpeta, evaluacion)
    with pytest.raises(CommandError, match="Faltan campos"):
        call_command("exportar_prediccion_ficticia")


def test_rechaza_datos_no_ficticios(carpeta, evaluacion):
    evaluacion["datos_ficticios"] = False
    escribir(carpeta, evaluacion)
    with pytest.raises(CommandError, match="datos_ficticios"):
        call_command("exportar_prediccion_ficticia")
