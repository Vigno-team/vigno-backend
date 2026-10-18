import pandas as pd

from apps.clima.prediccion.correlaciones import _holm, correlacion

INDICES = {"wi": "winkler", "hi": "huglin", "gst": "gst"}
OBJETIVOS = ["doy", "brix", "acidez", "ph"]


def _niveles(df: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    """Promedia por temporada: el clima solo cambia entre región-año."""
    amerine = df[df["fuente"] == "Amerine & Winkler"]
    napa = df[df["fuente"] == "Napa"]
    return [
        ("region_anio", amerine.groupby(["region", "anio"]).mean(numeric_only=True)),
        ("anio_cultivar", napa.groupby(["anio", "cultivar"]).mean(numeric_only=True)),
    ]


def correlacionar_clima_madurez(ruta_csv) -> list[dict]:
    """Spearman de cada índice contra cada objetivo; Holm dentro de cada nivel.

    Devuelve filas {indice, objetivo, nivel, n, rho, p, p_holm}.
    """
    df = pd.read_csv(ruta_csv)
    resultados = []
    for nivel, temporadas in _niveles(df):
        filas = []
        for columna, indice in INDICES.items():
            for objetivo in OBJETIVOS:
                if columna not in temporadas or objetivo not in temporadas:
                    continue
                pares = temporadas[[columna, objetivo]].dropna()
                medida = correlacion(pares[columna].tolist(), pares[objetivo].tolist())
                if medida["estado"] != "ok":
                    continue
                filas.append(
                    {
                        "indice": indice,
                        "objetivo": objetivo,
                        "nivel": nivel,
                        "n": medida["n"],
                        "rho": round(medida["rho"], 3),
                        "p_valor": medida["p_valor"],
                    }
                )
        _holm(filas)
        for fila in filas:
            fila["p"] = round(fila.pop("p_valor"), 4)
            fila["p_holm"] = round(fila.pop("p_ajustado_holm"), 4)
        resultados.extend(filas)
    return resultados
