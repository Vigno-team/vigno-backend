"""E1C-83: años análogos de cada temporada de VIGNO en el dataset ficticio.

Similitud: se estandarizan (z) las variables elegidas con la media y la desviación
de las temporadas ficticias, se mide la distancia euclidiana d entre la temporada
de VIGNO y cada temporada ficticia, y se convierte a similitud = 100 / (1 + d).
Una temporada idéntica da 100 %; la similitud baja a medida que crece la distancia.
"""

from datetime import date, timedelta

import pandas as pd

from apps.clima.models import IndiceClimatico

COLUMNA = {"winkler": "wi", "huglin": "hi", "gst": "gst"}
ESTACIONES = ("El Arenal", "San Clemente")
CLAVE = ["fuente", "region", "anio"]


def temporadas_ficticias(df: pd.DataFrame, calidad: pd.DataFrame | None = None) -> pd.DataFrame:
    """Una fila por temporada: Subset1 por región-año y Napa por año (región II)."""
    temporadas = df.groupby(CLAVE, as_index=False).agg(
        wi=("wi", "first"),
        hi=("hi", "first"),
        gst=("gst", "first"),
        doy=("doy", "mean"),
        doy_hs=("doy_hs", "mean"),
        brix=("brix", "median"),
    )
    if calidad is not None:
        temporadas = temporadas.merge(
            calidad[[*CLAVE, "pct_alta", "motivo_nulo"]], on=CLAVE, how="left"
        )
    return temporadas


def _numero(valor):
    return None if pd.isna(valor) else round(float(valor), 1)


def _origen(fila) -> str:
    if fila["fuente"] == "Napa":
        return f"Napa {fila['anio']}"
    return f"Región {fila['region']} {fila['anio']}"


def calcular_analogos(
    temp_vigno: dict,
    df_historico: pd.DataFrame,
    anio_inicio: int,
    variables=("winkler", "huglin"),
    calidad: pd.DataFrame | None = None,
    cantidad: int = 3,
) -> list[dict]:
    """Las `cantidad` temporadas ficticias más parecidas a `temp_vigno`."""
    desconocidas = [v for v in variables if v not in COLUMNA]
    if desconocidas:
        raise ValueError(f"Variables no soportadas: {desconocidas}")
    faltan = [v for v in variables if temp_vigno.get(v) is None]
    if faltan:
        raise ValueError(f"Faltan variables de la temporada: {faltan}")
    if df_historico.empty:
        return []

    columnas = [COLUMNA[v] for v in variables]
    df = temporadas_ficticias(df_historico, calidad).dropna(subset=columnas)
    if df.empty:
        return []

    diferencias = pd.DataFrame(index=df.index)
    for variable, columna in zip(variables, columnas, strict=True):
        desviacion = df[columna].std()
        if pd.isna(desviacion) or desviacion == 0:
            desviacion = 1.0
        diferencias[variable] = (df[columna] - temp_vigno[variable]) / desviacion

    df["distancia"] = (diferencias**2).sum(axis=1) ** 0.5
    df["explica"] = diferencias.abs().idxmin(axis=1)
    mejores = df.nsmallest(cantidad, "distancia")

    resultados = []
    for _, fila in mejores.iterrows():
        fecha = None
        if pd.notna(fila["doy_hs"]):
            fecha = date(anio_inicio, 1, 1) + timedelta(days=round(fila["doy_hs"]) - 1)
        resultados.append(
            {
                "origen": _origen(fila),
                "similitud_pct": round(100 / (1 + fila["distancia"]), 1),
                "doy": _numero(fila["doy"]),
                "fecha_equivalente": fecha.isoformat() if fecha else None,
                "calidad": {
                    "pct_alta": _numero(fila.get("pct_alta")),
                    "motivo_nulo": None
                    if pd.isna(fila.get("motivo_nulo"))
                    else fila["motivo_nulo"],
                },
                "brix": _numero(fila["brix"]),
                "explica": fila["explica"],
            }
        )
    return resultados


def indices_vigno() -> dict:
    """{(estacion, temporada): {"winkler": x, "huglin": y}} con índices confiables."""
    filas = IndiceClimatico.objects.filter(
        estacion__nombre__in=ESTACIONES, indice__in=["Winkler", "Huglin"], confiable=True
    ).select_related("estacion")
    temporadas = {}
    for fila in filas:
        temporadas.setdefault((fila.estacion, fila.temporada), {})[fila.indice.lower()] = fila.valor
    return temporadas


def obtener_analogos_vigno(df_historico: pd.DataFrame, calidad: pd.DataFrame | None = None):
    """Análogos de cada temporada de VIGNO con Winkler y Huglin confiables.

    Compara solo con Winkler y Huglin: el GST de VIGNO todavía no se calcula.
    """
    resultados = []
    for (estacion, temporada), indices in sorted(
        indices_vigno().items(), key=lambda item: (item[0][0].nombre, item[0][1])
    ):
        if indices.keys() != {"winkler", "huglin"}:
            continue
        resultados.append(
            {
                "estacion_id": estacion.codigo,
                "temporada": temporada,
                "indices": {"wi": indices["winkler"], "hi": indices["huglin"]},
                "anios_analogos": calcular_analogos(
                    indices, df_historico, int(temporada[:4]), calidad=calidad
                ),
            }
        )
    return resultados
