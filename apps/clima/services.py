import pandas as pd

from apps.clima.models import ConfiguracionCalidad, ResumenDiario
from apps.clima.temporadas import temporada_de


def horas_del_dia(fecha) -> int:
    tz = "America/Santiago"
    ini = pd.Timestamp(fecha).tz_localize(tz, nonexistent="shift_forward")
    fin = (pd.Timestamp(fecha) + pd.Timedelta(days=1)).tz_localize(tz, nonexistent="shift_forward")
    return int((fin - ini) / pd.Timedelta(hours=1))


def derivar_resumenes_diarios(df_ingesta: pd.DataFrame) -> list[ResumenDiario]:
    if df_ingesta.empty:
        return []

    df = df_ingesta.copy()
    config = ConfiguracionCalidad.obtener_config()

    ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df["fecha"] = ts.dt.tz_convert("America/Santiago").dt.date
    df = df.dropna(subset=["fecha", "frecuencia"])

    registros = []
    campos_update = [
        "tmax",
        "tmin",
        "tmedia",
        "amplitud_termica",
        "precipitacion",
        "origen",
        "horas_validas",
        "horas_esperadas",
        "confiable",
        "motivo_nulo",
    ]

    # Diarios (D)
    df_diario = df[df["frecuencia"] == "D"]
    for _, row in df_diario.iterrows():
        if ResumenDiario.objects.filter(
            estacion_id=row["estacion_id"], fecha=row["fecha"], origen="H"
        ).exists():
            continue

        tmax = (
            round(float(row.get("temperatura_maxima")), 2)
            if pd.notna(row.get("temperatura_maxima"))
            else None
        )
        tmin = (
            round(float(row.get("temperatura_minima")), 2)
            if pd.notna(row.get("temperatura_minima"))
            else None
        )
        tmedia = (
            round(float(row.get("temperatura_media")), 2)
            if pd.notna(row.get("temperatura_media"))
            else None
        )
        precipitacion = (
            round(float(row.get("precipitacion")), 2)
            if pd.notna(row.get("precipitacion"))
            else None
        )

        confiable = tmax is not None and tmin is not None
        amplitud = round(tmax - tmin, 2) if confiable else None

        es_nulo_total = tmax is None and tmin is None and tmedia is None
        motivo = (
            row.get("motivo_nulo") if es_nulo_total and pd.notna(row.get("motivo_nulo")) else None
        )

        registros.append(
            ResumenDiario(
                estacion_id=row["estacion_id"],
                fecha=row["fecha"],
                temporada=temporada_de(row["fecha"]),
                tmax=tmax,
                tmin=tmin,
                tmedia=tmedia,
                amplitud_termica=amplitud,
                precipitacion=precipitacion,
                origen="D",
                confiable=confiable,
                motivo_nulo=motivo,
            )
        )

    # Horarios (H)
    df_horario = df[df["frecuencia"] == "H"]
    if not df_horario.empty and "temperatura_media" in df_horario.columns:
        for (est_id, fecha), grupo in df_horario.groupby(["estacion_id", "fecha"]):
            serie_tmedia = grupo["temperatura_media"].dropna()
            horas_validas = int(serie_tmedia.count())
            esperadas = horas_del_dia(fecha)

            es_confiable = horas_validas >= config.horas_minimas_dia

            if horas_validas > 0:
                tmax = round(float(grupo["temperatura_maxima"].max()), 2)
                tmin = round(float(grupo["temperatura_minima"].min()), 2)
                tmedia = round(float(serie_tmedia.mean()), 2)
                amplitud = round(tmax - tmin, 2)
                precipitacion = (
                    round(float(grupo["precipitacion"].sum()), 2)
                    if "precipitacion" in grupo
                    else None
                )
            else:
                tmax = tmin = tmedia = amplitud = precipitacion = None
                es_confiable = False

            registros.append(
                ResumenDiario(
                    estacion_id=est_id,
                    fecha=fecha,
                    temporada=temporada_de(fecha),
                    tmax=tmax,
                    tmin=tmin,
                    tmedia=tmedia,
                    amplitud_termica=amplitud,
                    precipitacion=precipitacion,
                    origen="H",
                    horas_validas=horas_validas,
                    horas_esperadas=esperadas,
                    confiable=es_confiable,
                )
            )

    ResumenDiario.objects.bulk_create(
        registros,
        update_conflicts=True,
        unique_fields=["estacion_id", "fecha"],
        update_fields=campos_update,
    )
    return registros


# --- JSON CONTRACT FUNCTIONS ---


def resumen_diario(estacion_codigo: str, desde: str, hasta: str) -> dict:
    dias = ResumenDiario.objects.filter(
        estacion__codigo=estacion_codigo, fecha__range=[desde, hasta]
    ).order_by("fecha")
    data = {"estacion_id": estacion_codigo, "desde": desde, "hasta": hasta, "dias": []}

    for d in dias:
        dia_dict = {
            "fecha": d.fecha.strftime("%Y-%m-%d"),
            "tmax": d.tmax,
            "tmin": d.tmin,
            "tmedia": d.tmedia,
            "amplitud": d.amplitud_termica,
            "precipitacion": d.precipitacion,
        }
        if d.tmax is None and d.tmin is None and d.tmedia is None and d.motivo_nulo:
            dia_dict["motivo_nulo"] = d.motivo_nulo
        data["dias"].append(dia_dict)
    return data
