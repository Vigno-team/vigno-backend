import io
import json

import numpy as np
import pandas as pd
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

sklearn = pytest.importorskip("sklearn")

from apps.clima.prediccion.modelo import (  # noqa: E402
    FEATURES_PERMITIDAS,
    _doy_a_fecha,
    evaluar_por_anio,
    preparar_datos,
)


@pytest.fixture
def historico():
    filas = []
    for anio in (1939, 1940, 1941):
        for region, calor in (("I", 0), ("II", 1)):
            for cultivar, color, demora in (("Chardony", "White", 0), ("Merlot", "Red", 5)):
                filas.append(
                    {
                        "fuente": "Amerine & Winkler",
                        "anio": anio,
                        "region": region,
                        "cultivar": cultivar,
                        "color": color,
                        "gst": 17 + calor,
                        "wi": 1400 + 200 * calor + anio - 1939,
                        "hi": 1600 + 180 * calor,
                        "doy": 270 - calor * 10 + demora + anio - 1939,
                        "brix": 24,
                        "acidez": 0.6,
                        "ph": 3.4,
                    }
                )
    return pd.DataFrame(filas)


def test_holdout_separa_anios_y_conserva_identidad_california(historico):
    resultado, modelos = evaluar_por_anio(historico)
    validacion = resultado["validacion"]
    assert validacion["anios_entrenamiento"] == [1939, 1940]
    assert validacion["anios_prueba"] == [1941]
    assert validacion["filas_entrenamiento"] == 8
    assert validacion["filas_prueba"] == 4
    assert resultado["datos_ficticios"] is True
    assert "Scientific Data 9:271" in resultado["fuente"]
    assert set(resultado["features"]) == set(FEATURES_PERMITIDAS)
    assert set(resultado["metricas"]) == {"random_forest", "regresion_lineal", "promedio_regional"}
    esperadas = historico[historico.anio == 1941].to_dict("records")
    for fila, original in zip(resultado["predicciones"], esperadas, strict=True):
        for campo in ("fuente", "anio", "region", "cultivar", "color"):
            assert fila[campo] == original[campo]
        assert fila["doy_real"] == original["doy"]
        assert fila["diferencia_dias"] == pytest.approx(
            fila["doy_estimado"] - fila["doy_real"], abs=0.0001
        )
        assert fila["fecha_real"] == _doy_a_fecha(original["doy"], 1941)
        assert fila["prediccion"]["centro"].startswith("1941-")
        assert fila["prediccion"]["tipo"].endswith("no_calibrados")
        assert not {"subzona", "temporada", "cepa"}.intersection(fila)
    assert set(modelos) == {"random_forest", "regresion_lineal", "medias_region"}


def test_cambiar_objetivos_de_prueba_no_cambia_modelos_ni_base(historico):
    original, modelos_a = evaluar_por_anio(historico)
    cambiado = historico.copy()
    cambiado.loc[cambiado.anio == 1941, "doy"] += 40
    nuevo, modelos_b = evaluar_por_anio(cambiado)
    assert modelos_a["medias_region"] == modelos_b["medias_region"]
    assert modelos_a["medias_region"]["I"] == 273
    for a, b in zip(original["predicciones"], nuevo["predicciones"], strict=True):
        assert a["doy_estimado"] == b["doy_estimado"]
        assert a["doy_regresion_lineal"] == b["doy_regresion_lineal"]
    assert original["metricas"] != nuevo["metricas"]


def test_metricas_corresponden_a_todas_las_predicciones_de_prueba(historico):
    resultado, _ = evaluar_por_anio(historico)
    for modelo, campo in (
        ("random_forest", "doy_estimado"),
        ("regresion_lineal", "doy_regresion_lineal"),
        ("promedio_regional", "doy_promedio_regional"),
    ):
        errores = np.array([p[campo] - p["doy_real"] for p in resultado["predicciones"]])
        assert resultado["metricas"][modelo]["mae_dias"] == pytest.approx(
            np.abs(errores).mean(), abs=0.0001
        )
        assert resultado["metricas"][modelo]["rmse_dias"] == pytest.approx(
            np.sqrt((errores**2).mean()), abs=0.0001
        )


def test_variables_de_cosecha_no_entran_en_features(historico):
    X, y = preparar_datos(historico)
    cambiado = historico.assign(brix=999, acidez=999, ph=999, alcohol=999, doy_hs=999)
    X_otro, y_otro = preparar_datos(cambiado)
    pd.testing.assert_frame_equal(X, X_otro)
    pd.testing.assert_series_equal(y, y_otro)
    assert list(X.columns) == FEATURES_PERMITIDAS


def test_region_desconocida_no_se_convierte_en_iii(historico):
    historico.loc[0, "region"] = "VI"
    with pytest.raises(ValueError, match="Regiones desconocidas"):
        evaluar_por_anio(historico)


@pytest.mark.parametrize(
    "campo,valor", [("color", "inventado"), ("gst", np.inf), ("doy", 400), ("anio", 1941.5)]
)
def test_datos_invalidos_fallan(historico, campo, valor):
    historico[campo] = historico[campo].astype(object)
    historico.loc[0, campo] = valor
    with pytest.raises(ValueError):
        evaluar_por_anio(historico)


@pytest.mark.parametrize("anios", [[], [1900], [1939, 1940, 1941]])
def test_split_sin_datos_no_entrena(historico, anios):
    with pytest.raises(ValueError):
        evaluar_por_anio(historico, anios)


def test_sin_datos_validos_falla(historico):
    historico["gst"] = np.nan
    with pytest.raises(ValueError):
        evaluar_por_anio(historico)


def test_napa_queda_excluida_y_se_informa(historico):
    napa = historico.iloc[[0]].assign(fuente="Napa", anio=2000, color=None)
    resultado, _ = evaluar_por_anio(pd.concat([historico, napa], ignore_index=True))
    assert resultado["validacion"]["filas_otras_fuentes_excluidas"] == 1
    assert all(p["fuente"] == "Amerine & Winkler" for p in resultado["predicciones"])


def test_faltantes_no_crean_etiquetas_por_defecto(historico):
    with pytest.raises(ValueError, match="identificadores"):
        evaluar_por_anio(historico.drop(columns="cultivar"))


def test_codificacion_categorica_y_importancias_agrupadas(historico):
    resultado, modelos = evaluar_por_anio(historico)
    encoder = modelos["random_forest"].named_steps["preprocesar"].named_transformers_["categoricas"]
    assert list(encoder.categories_[0]) == ["I", "II"]
    assert set(resultado["importancias_random_forest"]) == set(FEATURES_PERMITIDAS)
    assert sum(resultado["importancias_random_forest"].values()) == pytest.approx(1, abs=0.00001)


def test_fechas_usan_anio_real_sin_desplazamiento():
    assert _doy_a_fecha(251, 1936) == "1936-09-07"
    assert _doy_a_fecha(60, 1940) == "1940-02-29"
    with pytest.raises(ValueError):
        _doy_a_fecha(366, 1941)


def test_coeficientes_reconstruyen_prediccion_lineal(historico):
    resultado, modelos = evaluar_por_anio(historico)
    X, _ = preparar_datos(historico[historico.anio == 1941])
    transformado = modelos["regresion_lineal"].named_steps["preprocesar"].transform(X)
    explicacion = resultado["regresion_lineal"]
    reconstruido = transformado @ np.array(list(explicacion["coeficientes"].values()))
    reconstruido += explicacion["intercepto_dias"]
    np.testing.assert_allclose(reconstruido, modelos["regresion_lineal"].predict(X))


def test_filas_incompletas_se_excluyen_tambien_de_base_y_metricas(historico):
    historico.loc[historico.index[-1], "gst"] = np.nan
    resultado, _ = evaluar_por_anio(historico)
    assert len(resultado["predicciones"]) == 3
    assert resultado["validacion"]["filas_historico_descartadas"] == 1
    assert all(m["n"] == 3 for m in resultado["metricas"].values())


def test_comando_guarda_evaluacion_y_modelos(historico, tmp_path, settings):
    settings.BASE_DIR = tmp_path
    carpeta = tmp_path / "data" / "ficticio"
    carpeta.mkdir(parents=True)
    historico.to_csv(carpeta / "cosechas.csv", index=False)
    salida = io.StringIO()
    call_command("entrenar_cosecha", stdout=salida)
    contenido = json.loads((carpeta / "prediccion_cosecha_california.json").read_text())
    assert contenido["validacion"]["anios_prueba"] == [1941]
    assert len(contenido["predicciones"]) == 4
    assert len(list((tmp_path / "apps/ml/artifacts").glob("*.joblib"))) == 1
    import joblib

    guardado = joblib.load(next((tmp_path / "apps/ml/artifacts").glob("*.joblib")))
    X, _ = preparar_datos(historico[historico.anio == 1941])
    predicciones = guardado["modelos"]["random_forest"].predict(X)
    np.testing.assert_allclose(
        predicciones, [p["doy_estimado"] for p in contenido["predicciones"]], atol=0.0001
    )
    assert guardado["version"] == contenido["version_modelo"]
    assert guardado["features"] == FEATURES_PERMITIDAS
    assert "MAE=" in salida.getvalue() and "RMSE=" in salida.getvalue()
    assert not (carpeta / "prediccion_cosecha_vigno.json").exists()


@pytest.mark.parametrize("contenido", [None, "", "fuente,anio\n"])
def test_comando_rechaza_archivo_ausente_o_vacio(tmp_path, settings, contenido):
    settings.BASE_DIR = tmp_path
    if contenido is not None:
        carpeta = tmp_path / "data/ficticio"
        carpeta.mkdir(parents=True)
        (carpeta / "cosechas.csv").write_text(contenido)
    with pytest.raises(CommandError):
        call_command("entrenar_cosecha")
    assert not (tmp_path / "apps/ml/artifacts").exists()
