from datetime import date, timedelta

import numpy as np
import pandas as pd

from apps.clima.models import IndiceClimatico


def temporadas_ficticias(df):
    """Una fila por temporada: Subset1 por región-año y Napa por año."""
    return df.groupby(["fuente", "region", "anio"], as_index=False).agg(
        wi=("wi", "first"),
        hi=("hi", "first"),
        gst=("gst", "first"),
        doy=("doy", "mean"),
        doy_hs=("doy_hs", "mean"),
        brix=("brix", "median"),
    )


def calcular_analogos(
    temp_vigno: dict, df_historico: pd.DataFrame, anio_inicio: int, variables=None
):
    if variables is None:
        variables = ["winkler", "huglin"]

    faltan = [v for v in variables if temp_vigno.get(v) is None]
    if faltan:
        raise ValueError(f"Faltan variables de la temporada: {faltan}")

    mapa_vars = {"winkler": "wi", "huglin": "hi", "gst": "gst"}
    columnas_req = [mapa_vars[v] for v in variables if v in mapa_vars]
    df = df_historico.dropna(subset=columnas_req).copy()
    if df.empty:
        return []

    df = temporadas_ficticias(df)
    z_scores_vigno = {}

    for var in variables:
        col = mapa_vars[var]
        mean_val = df[col].mean()
        std_val = df[col].std() if pd.notna(df[col].std()) and df[col].std() > 0 else 1.0
        df[f"z_{col}"] = (df[col] - mean_val) / std_val
        z_scores_vigno[var] = (temp_vigno[var] - mean_val) / std_val

    def evaluar_similitud(row):
        dist_sq = sum((row[f"z_{mapa_vars[v]}"] - z_scores_vigno[v]) ** 2 for v in variables)
        min_diff = min(variables, key=lambda v: abs(row[f"z_{mapa_vars[v]}"] - z_scores_vigno[v]))
        return pd.Series([np.sqrt(dist_sq), max(0, 100 / (1 + np.sqrt(dist_sq))), min_diff])

    df[["distancia", "similitud", "explicacion"]] = df.apply(evaluar_similitud, axis=1)
    df_top = df.sort_values("similitud", ascending=False).head(3)

    resultados = []
    for _, row in df_top.iterrows():
        try:
            fecha = date(anio_inicio, 1, 1) + timedelta(days=round(row.get("doy_hs")) - 1)
            fecha_iso = fecha.isoformat()
        except (TypeError, ValueError):
            fecha_iso = None

        resultados.append(
            {
                "temporada_ficticia": f"{row['fuente']} {row['region']} {row['anio']}".strip(),
                "similitud_pct": round(row["similitud"], 1),
                "variable_explicativa": row["explicacion"],
                "fecha_equivalente": fecha_iso,
                "brix": row.get("brix"),
            }
        )
    return resultados


def obtener_analogos_vigno(df_historico):
    """Obtiene los análogos iterando sobre temporadas confiables de la BD VIGNO."""
    temporadas = IndiceClimatico.objects.filter(
        estacion__in=["El Arenal", "San Clemente"], confiable=True
    )
    resultados = []
    for temp in temporadas:
        if not temp.winkler or not temp.huglin:
            continue
        anio_inicio = int(temp.temporada.split("-")[0])
        dict_vigno = {"winkler": temp.winkler, "huglin": temp.huglin}
        try:
            analogos = calcular_analogos(dict_vigno, df_historico, anio_inicio)
            resultados.append(
                {
                    "temporada": temp.temporada,
                    "estacion": temp.estacion.nombre,
                    "analogos": analogos,
                }
            )
        except ValueError:
            continue
    return resultados
