import pandas as pd
from django.db.models import Count, Max, Min, Q

from apps.clima.models import ConfiguracionCalidad, Estacion, ResumenDiario
from apps.clima.temporadas import rango_de, temporada_de

TZ = "America/Santiago"
HAY_DATO = (
    Q(tmax__isnull=False)
    | Q(tmin__isnull=False)
    | Q(tmedia__isnull=False)
    | Q(precipitacion__isnull=False)
)
RESOLUCION = {"D": "diaria", "H": "horaria"}


def horas_del_dia(fecha) -> int:
    ini = pd.Timestamp(fecha).tz_localize(TZ, nonexistent="shift_forward")
    fin = (pd.Timestamp(fecha) + pd.Timedelta(days=1)).tz_localize(TZ, nonexistent="shift_forward")
    return int((fin - ini) / pd.Timedelta(hours=1))


def _num(valor):
    """float redondeado a 2 decimales, o None si es nulo."""
    return round(float(valor), 2) if pd.notna(valor) else None


def _serie_temp(grupo: pd.DataFrame, preferida: str) -> pd.Series:
    """Usa la columna max/min si existe y tiene datos; si no, la temperatura horaria."""
    if preferida in grupo and grupo[preferida].notna().any():
        return grupo[preferida]
    return grupo["temperatura_media"]


def derivar_resumenes_diarios(df_ingesta: pd.DataFrame) -> list[ResumenDiario]:
    if df_ingesta.empty:
        return []

    df = df_ingesta.copy()
    config = ConfiguracionCalidad.obtener_config()

    ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df["fecha"] = ts.dt.tz_convert(TZ).dt.date
    df = df.dropna(subset=["fecha", "frecuencia"])

    campos_update = [
        "temporada",
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

    df_horario = df[df["frecuencia"] == "H"]
    df_diario = df[df["frecuencia"] == "D"]

    dias_h = set(map(tuple, df_horario[["estacion_id", "fecha"]].drop_duplicates().values))
    if not df_diario.empty:
        dias_h |= set(
            ResumenDiario.objects.filter(
                origen="H",
                estacion_id__in=df_diario["estacion_id"].unique().tolist(),
                fecha__in=df_diario["fecha"].unique().tolist(),
            ).values_list("estacion_id", "fecha")
        )

    registros = []

    # Diarios
    df_diario = df_diario.drop_duplicates(subset=["estacion_id", "fecha"], keep="last")
    for _, row in df_diario.iterrows():
        if (row["estacion_id"], row["fecha"]) in dias_h:
            continue

        tmax = _num(row.get("temperatura_maxima"))
        tmin = _num(row.get("temperatura_minima"))
        tmedia = _num(row.get("temperatura_media"))
        precipitacion = _num(row.get("precipitacion"))

        confiable = tmax is not None and tmin is not None
        amplitud = round(tmax - tmin, 2) if confiable else None

        motivo = None
        if tmax is None and tmin is None and tmedia is None:
            motivo_origen = row.get("motivo_nulo")
            motivo = motivo_origen if pd.notna(motivo_origen) else "Sin datos"

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

    # Horarios
    if not df_horario.empty and "temperatura_media" in df_horario.columns:
        for (est_id, fecha), grupo in df_horario.groupby(["estacion_id", "fecha"]):
            serie_tmedia = grupo["temperatura_media"].dropna()
            horas_validas = int(serie_tmedia.count())
            esperadas = horas_del_dia(fecha)
            motivo = None

            if horas_validas > 0:
                tmax = _num(_serie_temp(grupo, "temperatura_maxima").max())
                tmin = _num(_serie_temp(grupo, "temperatura_minima").min())
                tmedia = _num(serie_tmedia.mean())
                amplitud = round(tmax - tmin, 2) if tmax is not None and tmin is not None else None
                precipitacion = (
                    _num(grupo["precipitacion"].sum(min_count=1))
                    if "precipitacion" in grupo
                    else None
                )
                es_confiable = horas_validas >= config.horas_minimas_dia
            else:
                tmax = tmin = tmedia = amplitud = precipitacion = None
                es_confiable = False
                motivos = grupo["motivo_nulo"].dropna() if "motivo_nulo" in grupo else []
                motivo = motivos.iloc[0] if len(motivos) else "Sin datos horarios"

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
                    motivo_nulo=motivo,
                )
            )

    ResumenDiario.objects.bulk_create(
        registros,
        update_conflicts=True,
        unique_fields=["estacion", "fecha"],
        update_fields=campos_update,
    )
    return registros


# Funciones del contrato JSON


def resumen_diario(estacion_codigo: str, desde: str, hasta: str) -> dict:
    # Lanza Estacion.DoesNotExist si es que el código no existe
    estacion = Estacion.objects.get(codigo=estacion_codigo)
    dias = ResumenDiario.objects.filter(estacion=estacion, fecha__range=[desde, hasta]).order_by(
        "fecha"
    )
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


def completitud_por_temporada(estacion_codigo: str | None = None) -> list[dict]:
    qs = ResumenDiario.objects.all()
    if estacion_codigo:
        estacion = Estacion.objects.get(codigo=estacion_codigo)  # error si no existe
        qs = qs.filter(estacion=estacion)

    umbral = ConfiguracionCalidad.obtener_umbral()
    hoy = pd.Timestamp.now(tz=TZ).date()

    filas = (
        qs.values("estacion__codigo", "temporada")
        .annotate(
            n_tmax=Count("tmax"),
            n_tmin=Count("tmin"),
            n_tmedia=Count("tmedia"),
            n_precipitacion=Count("precipitacion"),
        )
        .order_by("estacion__codigo", "temporada")
    )

    resultado = []
    for f in filas:
        inicio, fin = rango_de(f["temporada"])
        fin = min(fin, hoy)
        total = max((fin - inicio).days + 1, 1)

        def pct(n, total=total):
            return round(min(n / total * 100, 100), 1)

        variables = {
            "tmax": pct(f["n_tmax"]),
            "tmin": pct(f["n_tmin"]),
            "tmedia": pct(f["n_tmedia"]),
            "precipitacion": pct(f["n_precipitacion"]),
        }
        item = {
            "estacion_id": f["estacion__codigo"],
            "temporada": f["temporada"],
            "variables": variables,
            "confiable": variables["tmax"] >= umbral and variables["tmin"] >= umbral,
        }
        if variables["precipitacion"] == 0:
            item["observacion"] = "sin datos de precipitación en la temporada"
        resultado.append(item)
    return resultado


def temporadas() -> list[str]:
    return list(
        ResumenDiario.objects.filter(HAY_DATO)
        .order_by("temporada")
        .values_list("temporada", flat=True)
        .distinct()
    )


def estaciones() -> list[dict]:
    umbral = ConfiguracionCalidad.obtener_umbral()
    resultado = []
    for est in Estacion.objects.order_by("nombre"):
        qs = ResumenDiario.objects.filter(estacion=est)
        agg = qs.filter(HAY_DATO).aggregate(
            inicio=Min("fecha"),
            fin=Max("fecha"),
            n_completos=Count("id", filter=Q(tmax__isnull=False, tmin__isnull=False)),
            n_tmax=Count("tmax"),
            n_tmin=Count("tmin"),
            n_tmedia=Count("tmedia"),
            n_precipitacion=Count("precipitacion"),
        )
        variables = [
            nombre
            for nombre, n in [
                ("tmax", agg["n_tmax"]),
                ("tmin", agg["n_tmin"]),
                ("tmedia", agg["n_tmedia"]),
                ("precipitacion", agg["n_precipitacion"]),
            ]
            if n > 0
        ]

        completitud = None
        if agg["inicio"]:
            dias_rango = (agg["fin"] - agg["inicio"]).days + 1
            completitud = round(agg["n_completos"] / dias_rango * 100, 1)

        origenes = set(qs.order_by().values_list("origen", flat=True).distinct())
        if len(origenes) == 1:
            resolucion = RESOLUCION[origenes.pop()]
        else:
            resolucion = "mixta" if origenes else None

        n_temporadas = qs.filter(HAY_DATO).order_by().values("temporada").distinct().count()

        resultado.append(
            {
                "id": est.codigo,
                "nombre": est.nombre,
                "subzona": est.subzona,
                "propietario": est.propietario,
                "variables": variables,
                "fecha_inicio": agg["inicio"].isoformat() if agg["inicio"] else None,
                "fecha_fin": agg["fin"].isoformat() if agg["fin"] else None,
                "temporadas_disponibles": n_temporadas,
                "calidad_dato": {
                    "completitud_pct": completitud,
                    "confiable": completitud is not None and completitud >= umbral,
                    "umbral_completitud_pct": umbral,
                    "resolucion_origen": resolucion,
                    "version_calculo": None,
                },
            }
        )
    return resultado
