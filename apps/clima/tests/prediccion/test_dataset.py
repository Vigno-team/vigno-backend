import os

import pandas as pd
import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.clima.prediccion.dataset import procesar_historico_ficticio


def _excels(tmp_path, df1=None, df2=None, df3=None):
    df1 = (
        df1
        if df1 is not None
        else pd.DataFrame(
            {
                "anio": [1935, 1935, 1935],
                "region": ["I", "I", "I"],
                "cultivar": ["Cabernet", "Cabernet", "Merlot"],
                "doy": [280.0, 280.0, None],
                "RecReg": ["Ignorar", "Ignorar", "Ignorar"],
            }
        )
    )
    df2 = (
        df2
        if df2 is not None
        else pd.DataFrame(
            {"anio": [1994], "cultivar": ["Chardonnay"], "doy": [240.0], "brix": [24.5]}
        )
    )
    df3 = (
        df3
        if df3 is not None
        else pd.DataFrame(
            {
                "anio": [1935, 1994],
                "region": ["I", "II"],
                "gst": [16.5, 17.2],
                "wi": [1500, 1800],
                "hi": [2000, 2200],
            }
        )
    )
    rutas = [tmp_path / f"Subset{i}.xlsx" for i in (1, 2, 3)]
    for df, ruta in zip((df1, df2, df3), rutas, strict=True):
        df.to_excel(ruta, index=False)
    return rutas


def test_procesamiento_ficticio_basico(tmp_path):
    ruta_out = tmp_path / "cosechas.csv"
    df_res = procesar_historico_ficticio(*_excels(tmp_path), ruta_out)

    assert os.path.exists(ruta_out)
    assert len(df_res) == 2
    assert "RecReg" not in df_res.columns

    napa_row = df_res[df_res["fuente"] == "Napa"].iloc[0]
    assert napa_row["region"] == "II"
    assert napa_row["doy_hs"] == 240.0 + 182

    aw_row = df_res[df_res["fuente"] == "Amerine & Winkler"].iloc[0]
    assert aw_row["wi"] == 1500


def test_falla_si_falta_una_columna(tmp_path):
    clima_sin_wi = pd.DataFrame({"anio": [1935], "region": ["I"], "gst": [16.5], "hi": [2000]})
    rutas = _excels(tmp_path, df3=clima_sin_wi)
    with pytest.raises(ValueError, match="Subset3 no trae las columnas \\['wi'\\]"):
        procesar_historico_ficticio(*rutas, tmp_path / "cosechas.csv")


def test_falla_si_el_clima_repite_region_anio(tmp_path):
    clima_diario = pd.DataFrame(
        {"anio": [1935, 1935], "region": ["I", "I"], "gst": [16, 17], "wi": [1, 2], "hi": [1, 2]}
    )
    rutas = _excels(tmp_path, df3=clima_diario)
    with pytest.raises(pd.errors.MergeError):
        procesar_historico_ficticio(*rutas, tmp_path / "cosechas.csv")


def test_comando_falla_sin_los_excel(tmp_path, settings):
    settings.BASE_DIR = tmp_path
    with pytest.raises(CommandError, match="Subset1.xlsx"):
        call_command("cargar_dataset_ficticio")
