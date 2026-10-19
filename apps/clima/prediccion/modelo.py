from datetime import datetime, timedelta

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression

FEATURES_PERMITIDAS = ["GST", "Winkler", "Huglin", "region", "color"]


def preparar_datos(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    # Renombrar columnas del CSV sintético para que coincidan con nuestro estándar
    mapeo_columnas = {
        "gst": "GST",
        "wi": "Winkler",
        "hi": "Huglin",
        "anio": "anho_cosecha",
        "cultivar": "cepa",
    }
    df = df.rename(columns=mapeo_columnas)

    columnas_requeridas = FEATURES_PERMITIDAS + ["doy"]

    # Nos aseguramos de trabajar solo con filas que tengan la información completa
    df_limpio = df.dropna(subset=columnas_requeridas).copy()

    # Codificación de región (I a V, o romana a número)
    if "region" in df_limpio.columns and df_limpio["region"].dtype == "object":
        mapa_region = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}
        df_limpio["region"] = df_limpio["region"].map(mapa_region).fillna(3)

    # Codificación de color (White/Red o Blanco/Tinto a binario)
    if "color" in df_limpio.columns and df_limpio["color"].dtype == "object":
        # Asignamos 1 si es Tinto o Red, 0 si es Blanco o White
        df_limpio["color"] = df_limpio["color"].str.lower().isin(["tinto", "red"]).astype(int)

    X = df_limpio[FEATURES_PERMITIDAS]
    y = df_limpio["doy"]

    return X, y


def entrenar_modelos(
    X: pd.DataFrame, y: pd.Series
) -> tuple[RandomForestRegressor, LinearRegression]:
    rf = RandomForestRegressor(n_estimators=100, random_state=42, n_jobs=-1)
    lr = LinearRegression()

    rf.fit(X, y)
    lr.fit(X, y)

    return rf, lr


def _doy_a_fecha(doy: float, anho: int) -> str:
    doy_int = int(round(doy))
    fecha = datetime(anho, 1, 1) + timedelta(days=doy_int - 1)
    return fecha.strftime("%Y-%m-%d")


def predecir_ventana(
    modelo_rf: RandomForestRegressor, X_in: pd.DataFrame, anho_cosecha: int
) -> dict:
    # Predicciones de cada árbol individual para armar la distribución
    predicciones_arboles = [arbol.predict(X_in.values)[0] for arbol in modelo_rf.estimators_]

    p10 = np.percentile(predicciones_arboles, 10)
    p90 = np.percentile(predicciones_arboles, 90)
    mediana = np.percentile(predicciones_arboles, 50)

    incertidumbre = (p90 - p10) / 2

    return {
        "centro": _doy_a_fecha(mediana, anho_cosecha),
        "desde": _doy_a_fecha(p10, anho_cosecha),
        "hasta": _doy_a_fecha(p90, anho_cosecha),
        "incertidumbre_dias": round(incertidumbre),
    }


def extraer_justificacion(modelo_rf: RandomForestRegressor) -> dict:
    importancias = np.round(modelo_rf.feature_importances_, 3)
    return dict(zip(FEATURES_PERMITIDAS, importancias, strict=False))
