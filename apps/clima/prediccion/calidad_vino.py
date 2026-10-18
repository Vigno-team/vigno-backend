import pandas as pd

# IMPORTANTE: Reemplaza estos 5 valores con los exactos de la hoja 'metadata' del Excel real cuando lo tengas
NIVELES_RECOMMEND = ["Nivel1", "Nivel2", "Nivel3", "Nivel4", "Nivel5"]
ESCALA = dict(zip(NIVELES_RECOMMEND, ["alta", "alta", "media", "baja", "baja"]))


def calidad_por_temporada(df):
    """Una fila por temporada: Subset1 por región-año y Napa por año."""
    s1 = df[df["fuente"] == "Amerine & Winkler"].copy()
    desconocidos = set(s1["recommend"].dropna()) - set(ESCALA)
    if desconocidos:
        raise ValueError(f"Valores de recommend sin mapeo: {sorted(desconocidos)}")

    s1["calidad"] = s1["recommend"].map(ESCALA)
    amerine = s1.groupby(["fuente", "region", "anio"], as_index=False).agg(
        pct_alta=("calidad", lambda c: round((c == "alta").sum() / c.notna().sum() * 100, 1)),
        brix_mediana=("brix", "median"),
        acidez_mediana=("acidez", "median"),
        ph_mediana=("ph", "median"),
    )

    napa = (
        df[df["fuente"] == "Napa"]
        .groupby(["fuente", "region", "anio"], as_index=False)
        .agg(brix_mediana=("brix", "median"))
    )
    napa["pct_alta"] = None
    napa["motivo_nulo"] = "Napa solo trae °Brix; no tiene evaluación de calidad."

    return pd.concat([amerine, napa], ignore_index=True)
