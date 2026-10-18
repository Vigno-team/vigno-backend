import pandas as pd

# Etiquetas originales de Subset1.xls, Figshare 19807777 (CC BY 4.0).
# Recommend describe recomendación del cultivar, no una cata de cada cosecha.
# Escala provisional de alta/media/baja, a confirmar con el enólogo.
NIVELES_RECOMMEND = [
    "Particularly recommended",
    "Limited recommendation",
    "Not recommended",
]
ESCALA = dict(zip(NIVELES_RECOMMEND, ["alta", "media", "baja"], strict=True))
# No son grados de calidad: se excluyen del denominador de pct_alta.
ESCALA.update({"Not fully tested": None, "Table grape": None})


def _pct_alta(calidades: pd.Series) -> float | None:
    evaluadas = calidades.dropna()
    if evaluadas.empty:
        return None
    return round((evaluadas == "alta").mean() * 100, 1)


def calidad_por_temporada(df: pd.DataFrame) -> pd.DataFrame:
    """Una fila por temporada: Subset1 por región-año y Napa por año."""
    s1 = df[df["fuente"] == "Amerine & Winkler"].copy()
    desconocidos = set(s1["recommend"].dropna()) - set(ESCALA)
    if desconocidos:
        raise ValueError(f"Valores de recommend sin mapeo: {sorted(desconocidos)}")

    s1["calidad"] = s1["recommend"].map(ESCALA)
    amerine = s1.groupby(["fuente", "region", "anio"], as_index=False).agg(
        pct_alta=("calidad", _pct_alta),
        brix_mediana=("brix", "median"),
        acidez_mediana=("acidez", "median"),
        ph_mediana=("ph", "median"),
    )
    amerine["pct_alta"] = amerine["pct_alta"].astype(float)
    amerine["motivo_nulo"] = (
        amerine["pct_alta"].isna().map({True: "La temporada no tiene evaluaciones.", False: None})
    )

    napa = (
        df[df["fuente"] == "Napa"]
        .groupby(["fuente", "region", "anio"], as_index=False)
        .agg(brix_mediana=("brix", "median"))
    )
    napa["motivo_nulo"] = "Napa solo trae °Brix; no tiene evaluación de calidad."
    napa = napa.reindex(columns=amerine.columns).astype(amerine.dtypes.to_dict())

    return pd.concat([amerine, napa], ignore_index=True)
