import pandas as pd

from apps.clima.prediccion.correlaciones import _holm, correlacion


def correlacionar_clima_madurez(ruta_csv: str):
    df = pd.read_csv(ruta_csv)
    df_amerine = (
        df[df["fuente"] == "Amerine & Winkler"]
        .groupby(["region", "anio"])
        .mean(numeric_only=True)
        .reset_index()
    )
    df_napa = (
        df[df["fuente"] == "Napa"]
        .groupby(["anio", "cultivar"])
        .mean(numeric_only=True)
        .reset_index()
    )

    niveles = [("region_anio", df_amerine), ("anio_cultivar", df_napa)]
    mapa_ind = {"wi": "winkler", "hi": "huglin", "gst": "gst"}
    objetivos = ["doy", "brix", "acidez", "ph"]

    resultados = []
    for nombre_nivel, df_nivel in niveles:
        res_nivel = []
        for col_ind, nom_ind in mapa_ind.items():
            for obj in objetivos:
                if col_ind not in df_nivel.columns or obj not in df_nivel.columns:
                    continue
                valid = df_nivel[[col_ind, obj]].dropna()
                n = len(valid)
                if n < 5:
                    continue

                rho, p_val = correlacion(valid[col_ind].values, valid[obj].values)
                if rho is not None:
                    res_nivel.append(
                        {
                            "indice": nom_ind,
                            "objetivo": obj,
                            "nivel": nombre_nivel,
                            "n": n,
                            "rho": round(rho, 3),
                            "p": p_val,
                        }
                    )

        if res_nivel:
            res_nivel = _holm(res_nivel)
            for r in res_nivel:
                if "p_valor" in r:
                    r["p"] = round(r["p_valor"], 4)
                    del r["p_valor"]
                if "p_ajustado_holm" in r:
                    r["p_holm"] = round(r["p_ajustado_holm"], 4)
                    del r["p_ajustado_holm"]
            resultados.extend(res_nivel)
    return resultados
