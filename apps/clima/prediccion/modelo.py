from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

FEATURES_PERMITIDAS = ["GST", "Winkler", "Huglin", "region", "color"]
FUENTE_HISTORICA = "Amerine & Winkler"
FUENTE_DATASET = "Bai et al. (2022), Scientific Data 9:271"
URL_DATASET = "https://doi.org/10.6084/m9.figshare.19807777.v1"


def preparar_datos(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Solo clima, región y color; nunca variables medidas en la cosecha."""
    datos = df.rename(columns={"gst": "GST", "wi": "Winkler", "hi": "Huglin"}).copy()
    requeridas = FEATURES_PERMITIDAS + ["doy"]
    faltan = [c for c in requeridas if c not in datos]
    if faltan:
        raise ValueError(f"Faltan columnas: {faltan}")
    if datos.columns.duplicated().any():
        raise ValueError("Hay columnas duplicadas después de normalizar sus nombres")
    regiones = datos["region"].dropna()
    desconocidas = set(regiones) - {"I", "II", "III", "IV", "V"}
    if desconocidas:
        raise ValueError(f"Regiones desconocidas: {sorted(map(str, desconocidas))}")
    colores = datos["color"].dropna()
    desconocidos = set(colores) - {"White", "Red", "blanco", "tinto"}
    if desconocidos:
        raise ValueError(f"Colores desconocidos: {sorted(map(str, desconocidos))}")
    for columna in ("GST", "Winkler", "Huglin", "doy"):
        datos[columna] = pd.to_numeric(datos[columna], errors="raise")
        presentes = datos[columna].dropna()
        if not np.isfinite(presentes).all():
            raise ValueError(f"{columna} contiene valores no finitos")
    datos = datos.dropna(subset=requeridas)
    if not datos["doy"].between(1, 366).all():
        raise ValueError("doy debe estar entre 1 y 366")
    datos["color"] = datos["color"].replace({"blanco": "White", "tinto": "Red"})
    return datos[FEATURES_PERMITIDAS], datos["doy"]


def _pipeline(estimador):
    preprocesar = ColumnTransformer(
        [
            ("numericas", "passthrough", ["GST", "Winkler", "Huglin"]),
            ("categoricas", OneHotEncoder(handle_unknown="ignore"), ["region", "color"]),
        ]
    )
    return Pipeline([("preprocesar", preprocesar), ("modelo", estimador)])


def entrenar_modelos(X: pd.DataFrame, y: pd.Series) -> tuple[Pipeline, Pipeline]:
    if X.empty:
        raise ValueError("No hay datos válidos para entrenar")
    rf = _pipeline(RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1))
    lr = _pipeline(LinearRegression())
    rf.fit(X, y)
    lr.fit(X, y)
    return rf, lr


def _doy_a_fecha(doy: float, anho: int) -> str:
    fecha = datetime(anho, 1, 1) + timedelta(days=int(round(doy)) - 1)
    if fecha.year != anho:
        raise ValueError(f"El día {doy} no pertenece al año {anho}")
    return fecha.strftime("%Y-%m-%d")


def predecir_ventana(modelo_rf: Pipeline, X_in: pd.DataFrame, anho_cosecha: int) -> dict:
    if len(X_in) != 1:
        raise ValueError("La ventana requiere exactamente una fila")
    transformado = modelo_rf.named_steps["preprocesar"].transform(X_in)
    arboles = modelo_rf.named_steps["modelo"].estimators_
    predicciones = [arbol.predict(transformado)[0] for arbol in arboles]
    p10, p90 = np.percentile(predicciones, [10, 90])
    estimado = float(modelo_rf.predict(X_in)[0])
    return {
        "centro": _doy_a_fecha(estimado, anho_cosecha),
        "desde": _doy_a_fecha(float(p10), anho_cosecha),
        "hasta": _doy_a_fecha(float(p90), anho_cosecha),
        "dispersion_dias": round(float((p90 - p10) / 2), 2),
        "tipo": "percentiles_10_90_entre_arboles_no_calibrados",
    }


def extraer_justificacion(modelo_rf: Pipeline) -> dict:
    nombres = modelo_rf.named_steps["preprocesar"].get_feature_names_out()
    importancias = modelo_rf.named_steps["modelo"].feature_importances_
    agrupadas = dict.fromkeys(FEATURES_PERMITIDAS, 0.0)
    for nombre, importancia in zip(nombres, importancias, strict=True):
        columna = nombre.split("__", 1)[1]
        if columna.startswith("region_"):
            columna = "region"
        elif columna.startswith("color_"):
            columna = "color"
        agrupadas[columna] += float(importancia)
    return {nombre: round(valor, 6) for nombre, valor in agrupadas.items()}


def coeficientes_lineales(modelo_lr: Pipeline) -> dict:
    """Coeficientes en unidades originales; asociación, no efecto causal."""
    nombres = modelo_lr.named_steps["preprocesar"].get_feature_names_out()
    modelo = modelo_lr.named_steps["modelo"]
    return {
        "intercepto_dias": float(modelo.intercept_),
        "coeficientes": {
            nombre.split("__", 1)[1]: float(valor)
            for nombre, valor in zip(nombres, modelo.coef_, strict=True)
        },
        "nota": (
            "Clima en unidades originales; región y color con one-hot. "
            "Los coeficientes dependen de la codificación y de índices correlacionados; "
            "no representan efectos causales ni un ranking de importancia."
        ),
    }


def evaluar_por_anio(df: pd.DataFrame, anios_prueba=(1941,)) -> tuple[dict, dict]:
    """Holdout de años completos de California; Napa se reserva para E1C-87."""
    faltan = [c for c in ("fuente", "region", "anio", "cultivar", "color") if c not in df]
    if faltan:
        raise ValueError(f"Faltan identificadores del CSV: {faltan}")
    datos = df.loc[df["fuente"] == FUENTE_HISTORICA].copy().reset_index(drop=True)
    if datos.empty:
        raise ValueError("No hay filas de Amerine & Winkler para evaluar")
    originales = len(datos)
    datos = datos.dropna(subset=["anio", "cultivar"])
    anios = pd.to_numeric(datos["anio"], errors="raise")
    if not np.isfinite(anios).all() or (anios % 1 != 0).any() or not anios.between(1, 9998).all():
        raise ValueError("anio debe contener años enteros válidos")
    datos["anio"] = anios.astype(int)
    X, y = preparar_datos(datos)
    datos = datos.loc[X.index]
    for indice, fila in datos.iterrows():
        _doy_a_fecha(float(y.loc[indice]), int(fila["anio"]))
    seleccion = sorted(set(anios_prueba))
    if not seleccion:
        raise ValueError("Indica al menos un año de prueba")
    faltan_anios = set(seleccion) - set(datos["anio"])
    if faltan_anios:
        raise ValueError(f"Años de prueba sin datos válidos: {sorted(faltan_anios)}")
    prueba = datos["anio"].isin(seleccion)
    X_train, X_test = X.loc[~prueba], X.loc[prueba]
    y_train, y_test = y.loc[~prueba], y.loc[prueba]
    if X_train.empty or X_test.empty:
        raise ValueError(
            "Se necesitan años distintos con datos válidos para entrenamiento y prueba"
        )
    rf, lr = entrenar_modelos(X_train, y_train)
    # El promedio regional usa exclusivamente las observaciones de entrenamiento.
    medias = y_train.groupby(X_train["region"]).mean()
    base = X_test["region"].map(medias)
    if base.isna().any():
        raise ValueError("Hay regiones de prueba sin histórico para la base regional")
    estimaciones = {
        "random_forest": rf.predict(X_test),
        "regresion_lineal": lr.predict(X_test),
        "promedio_regional": base.to_numpy(),
    }
    metricas = {
        nombre: {
            "mae_dias": round(float(mean_absolute_error(y_test, pred)), 4),
            "rmse_dias": round(float(np.sqrt(mean_squared_error(y_test, pred))), 4),
            "n": len(y_test),
        }
        for nombre, pred in estimaciones.items()
    }
    filas = []
    for posicion, (indice, fila) in enumerate(datos.loc[prueba].iterrows()):
        real = float(y_test.loc[indice])
        estimado = float(estimaciones["random_forest"][posicion])
        filas.append(
            {
                "fuente": fila["fuente"],
                "region": fila["region"],
                "anio": int(fila["anio"]),
                "cultivar": fila["cultivar"],
                "color": fila["color"],
                "doy_real": real,
                "doy_estimado": round(estimado, 4),
                "diferencia_dias": round(estimado - real, 4),
                "fecha_real": _doy_a_fecha(real, int(fila["anio"])),
                "prediccion": predecir_ventana(rf, X_test.loc[[indice]], int(fila["anio"])),
                "doy_regresion_lineal": round(float(estimaciones["regresion_lineal"][posicion]), 4),
                "doy_promedio_regional": round(
                    float(estimaciones["promedio_regional"][posicion]), 4
                ),
            }
        )
    resultado = {
        "datos_ficticios": True,
        "fuente": FUENTE_DATASET,
        "dataset_url": URL_DATASET,
        "pais": "California, Estados Unidos",
        "validacion": {
            "metodo": "holdout_por_anio",
            "anios_entrenamiento": sorted(set(datos.loc[~prueba, "anio"].tolist())),
            "anios_prueba": seleccion,
            "filas_entrenamiento": len(X_train),
            "filas_prueba": len(X_test),
            "filas_historico_descartadas": originales - len(datos),
            "filas_otras_fuentes_excluidas": len(df) - originales,
            "nota": "Napa queda para E1C-87. La dispersión entre árboles no es un intervalo calibrado.",
        },
        "features": FEATURES_PERMITIDAS,
        "metricas": metricas,
        "importancias_random_forest": extraer_justificacion(rf),
        "regresion_lineal": coeficientes_lineales(lr),
        "comparacion_base": {
            "rf_mejora_mae": metricas["random_forest"]["mae_dias"]
            < metricas["promedio_regional"]["mae_dias"],
            "rf_mejora_rmse": metricas["random_forest"]["rmse_dias"]
            < metricas["promedio_regional"]["rmse_dias"],
        },
        "predicciones": filas,
    }
    return resultado, {
        "random_forest": rf,
        "regresion_lineal": lr,
        "medias_region": medias.to_dict(),
    }
