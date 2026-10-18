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


REGIONES = {1: "I", 2: "II", 3: "III", 4: "IV", 5: "V"}


def _leer_cosechas(ruta, subset):
    """Lee la hoja data original o una tabla ya normalizada."""
    with pd.ExcelFile(ruta) as libro:
        df = pd.read_excel(libro, sheet_name="data" if "data" in libro.sheet_names else 0)
    if "cultivar" in df.columns:
        return df
    if subset == 1:
        df = df.rename(
            columns={
                "Cultivar": "cultivar",
                "Color": "color",
                "Recommend": "recommend",
                "Reg": "region",
                "DOY": "doy",
                "Must.Brix": "brix",
                "Must.Tacid": "acidez",
                "Must.pH": "ph",
            }
        )
        if "Harvest date" not in df:
            raise ValueError("Subset1 no trae Harvest date para obtener el año")
        df["anio"] = pd.to_datetime(df["Harvest date"], errors="raise").dt.year.astype("Int64")
        if "region" in df:
            if not df["region"].isin(REGIONES).all():
                raise ValueError("Subset1 contiene regiones fuera de 1 a 5")
            df["region"] = df["region"].map(REGIONES)
    else:
        df = df.rename(
            columns={
                "Year": "anio",
                "Cultivar": "cultivar",
                "Harvest date": "doy",
                "Brix": "brix",
            }
        )
    for campo in ("doy", "brix", "acidez", "ph"):
        if campo in df:
            df[campo] = pd.to_numeric(df[campo], errors="raise")
    return df


def _leer_clima(ruta):
    """Los índices anuales están en I:L, separados de las temperaturas diarias."""
    with pd.ExcelFile(ruta) as libro:
        if not any(nombre.startswith("Region_") for nombre in libro.sheet_names):
            return pd.read_excel(libro)
        tablas = []
        for numero, region in REGIONES.items():
            hoja = f"Region_{numero}"
            if hoja not in libro.sheet_names:
                raise ValueError(f"Subset3 no trae la hoja {hoja}")
            df = pd.read_excel(libro, sheet_name=hoja, usecols="I:L").dropna(how="all")
            if list(df.columns)[1:] != ["GST", "WI", "HI"] or df.columns[0] not in (
                "Year",
                "Year.1",
            ):
                raise ValueError(f"{hoja}: se esperaban Year, GST, WI, HI en I:L")
            df.columns = ["anio", "gst", "wi", "hi"]
            df["anio"] = pd.to_numeric(df["anio"], errors="raise").astype("Int64")
            df["region"] = region
            tablas.append(df)
    return pd.concat(tablas, ignore_index=True)


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
    df1 = _leer_cosechas(ruta_subset1, 1)
    df2 = _leer_cosechas(ruta_subset2, 2)
    df_clima = _leer_clima(ruta_subset3)
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
