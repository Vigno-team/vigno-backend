import pandas as pd
import pytest

from apps.clima.prediccion.modelo import entrenar_modelos, predecir_ventana, preparar_datos


@pytest.fixture
def df_dummy():
    return pd.DataFrame(
        {
            "GST": [18.1, 19.2, 17.5, 18.8, 19.0],
            "Winkler": [1500, 1600, 1400, 1550, 1580],
            "Huglin": [2100, 2200, 2000, 2150, 2180],
            "region": ["IV", "IV", "III", "IV", "V"],
            "color": ["tinto", "tinto", "blanco", "tinto", "tinto"],
            "doy": [80, 75, 90, 78, 72],
            "anho_cosecha": [2022, 2023, 2024, 2025, 2026],
        }
    )


def test_pipeline_entrenamiento_y_prediccion(df_dummy):
    # Preparar datos
    X, y = preparar_datos(df_dummy)
    assert list(X.columns) == ["GST", "Winkler", "Huglin", "region", "color"]
    assert len(X) == 5

    # Validar codificación
    assert X.iloc[0]["color"] == 1  # tinto -> 1
    assert X.iloc[2]["color"] == 0  # blanco -> 0
    assert X.iloc[0]["region"] == 4  # IV -> 4

    # Entrenar
    rf, lr = entrenar_modelos(X, y)
    assert rf is not None
    assert lr is not None

    # Predecir
    X_in = X.iloc[[0]]
    ventana = predecir_ventana(rf, X_in, 2026)

    assert "centro" in ventana
    assert "desde" in ventana
    assert "hasta" in ventana
    assert "incertidumbre_dias" in ventana
    assert isinstance(ventana["incertidumbre_dias"], int)

    # Validar que devolvió una fecha válida de Chile
    assert ventana["centro"].startswith("2026-")