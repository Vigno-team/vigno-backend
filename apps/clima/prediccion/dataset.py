from pathlib import Path

import pandas as pd

# Columnas sin las que no se puede unir cosecha con clima.
REQUERIDAS = {
    "Subset1": ["anio", "region", "cultivar", "doy"],
    "Subset2": ["anio", "cultivar", "doy"],
    "Subset3": ["anio", "region", "gst", "wi", "hi"],
}

COLUMNAS = [
    "fuente",
    "anio",
    "region",
    "cultivar",
    "color",
    "doy",
    "brix",
    "acidez",
    "ph",
    "recommend",
    "gst",
    "wi",
    "hi",
    "doy_hs",
]


def _validar(df: pd.DataFrame, nombre: str) -> None:
    faltan = [c for c in REQUERIDAS[nombre] if c not in df.columns]
    if faltan:
        raise ValueError(f"{nombre} no trae las columnas {faltan}. Trae: {list(df.columns)}")


def procesar_historico_ficticio(
    ruta_subset1: str, ruta_subset2: str, ruta_subset3: str, ruta_salida: str
) -> pd.DataFrame:
    """Une las cosechas de California con su clima y escribe cosechas.csv.

    doy_hs = doy + 182: día equivalente en el hemisferio sur, contado desde el
    1 de enero del primer año de la temporada. Puede pasar de 365 porque la
    cosecha cae en el año siguiente (doy 255 + 182 = 437 ≈ 12 de marzo).
    """
    df1 = pd.read_excel(ruta_subset1)
    df2 = pd.read_excel(ruta_subset2)
    df_clima = pd.read_excel(ruta_subset3)
    for df, nombre in ((df1, "Subset1"), (df2, "Subset2"), (df_clima, "Subset3")):
        _validar(df, nombre)

    df1["fuente"] = "Amerine & Winkler"
    df2["fuente"] = "Napa"
    df2["region"] = "II"

    df_cosechas = pd.concat([df1, df2], ignore_index=True)
    df_cosechas = df_cosechas.dropna(subset=["doy"])
    df_cosechas = df_cosechas.drop(columns=["RecReg"], errors="ignore").drop_duplicates()

    # many_to_one: si Subset3 trae más de una fila por año y región, falla en vez
    # de repetir cada cosecha una vez por fila de clima.
    df_final = pd.merge(
        df_cosechas, df_clima, on=["anio", "region"], how="left", validate="many_to_one"
    )
    df_final["doy_hs"] = df_final["doy"] + 182

    # Napa no trae color, acidez, pH ni recommend: quedan vacías.
    df_final = df_final.reindex(columns=COLUMNAS)

    Path(ruta_salida).parent.mkdir(parents=True, exist_ok=True)
    df_final.to_csv(ruta_salida, index=False, encoding="utf-8")
    return df_final
