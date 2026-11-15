import pandas as pd
from django.db.models import Count, Max, Min, Q
from django.utils import timezone

from apps.clima.models import ConfiguracionCalidad, Estacion, ResumenDiario
from apps.clima.rangos import MOTIVO_RANGO, VARIABLES
from apps.clima.temporadas import rango_temporada, temporada_de

HAY_DATO = (
    Q(tmax__isnull=False)
    | Q(tmin__isnull=False)
    | Q(tmedia__isnull=False)
    | Q(precipitacion__isnull=False)
    | Q(humedad_media__isnull=False)
    | Q(radiacion_maxima__isnull=False)
    | Q(viento_maximo__isnull=False)
)
MOTIVO_EXCLUIDO = "Variables excluidas por el administrador"
# Una temporada excluida conserva su ficha con índices nulos y su explicación.
HAY_INFORMACION = HAY_DATO | Q(motivo_nulo__contains=MOTIVO_EXCLUIDO)
VARIABLES_RESUMEN = {
    **VARIABLES,
    "humedad_media": "humedad_media",
    "radiacion_maxima": "radiacion_maxima",
    "viento_maximo": "viento_maximo",
}
RESOLUCION = {"D": "diaria", "H": "horaria"}


def horas_del_dia(fecha) -> int:
    tz = timezone.get_current_timezone_name()
    ini = pd.Timestamp(fecha).tz_localize(tz, nonexistent="shift_forward")
    fin = (pd.Timestamp(fecha) + pd.Timedelta(days=1)).tz_localize(tz, nonexistent="shift_forward")
    return int((fin - ini) / pd.Timedelta(hours=1))


def _num(valor):
    """float redondeado a 2 decimales, o None si es nulo."""
    return round(float(valor), 2) if pd.notna(valor) else None


def _serie_temp(grupo: pd.DataFrame, preferida: str) -> pd.Series:
    """Usa la columna max/min si existe y tiene datos; si no, la temperatura horaria."""
    if preferida in grupo and grupo[preferida].notna().any():
        return grupo[preferida]
    if grupo[f"{preferida}_excluido"].any():
        return grupo[preferida]
    return grupo["temperatura_media"]


def derivar_resumenes_diarios(df_ingesta: pd.DataFrame) -> list[ResumenDiario]:
    if df_ingesta.empty:
        return []

    df = df_ingesta.copy()
    config = ConfiguracionCalidad.obtener_config()
    # Mantener las marcas en el dataframe para invalidar la variable del día,
    # incluso si hay otras horas válidas; nunca agregar un valor marcado.
    for variable in VARIABLES_RESUMEN:
        marca = f"{variable}_fuera_de_rango"
        excluido = f"{variable}_excluido"
        if excluido not in df:
            df[excluido] = False
        df[excluido] = df[excluido].eq(True)
        if marca not in df:
            df[marca] = False
        df[marca] = df[marca].eq(True)
        # Un dato fuera de rango que se excluyó ya no invalida las otras horas.
        df.loc[df[excluido], marca] = False
        if variable not in df:
            df[variable] = float("nan")
        df.loc[df[marca] | df[excluido], variable] = float("nan")

    ts = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df["fecha"] = ts.dt.tz_convert(timezone.get_current_timezone_name()).dt.date
    df = df.dropna(subset=["fecha", "frecuencia"])
    if "origen_manual" not in df:
        df["origen_manual"] = False
    df["origen_manual"] = df["origen_manual"].fillna(False).astype(bool)
    manuales = df.groupby(["estacion_id", "fecha"])["origen_manual"].any()

    campos_update = [
        "temporada",
        "tmax",
        "tmin",
        "tmedia",
        "amplitud_termica",
        "precipitacion",
        "humedad_media",
        "radiacion_maxima",
        "viento_maximo",
        "origen",
        "horas_validas",
        "horas_esperadas",
        "confiable",
        "motivo_nulo",
        "corregido_a_mano",
    ]

    df_horario = df[df["frecuencia"] == "H"]
    df_diario = df[df["frecuencia"] == "D"]

    dias_h = set(map(tuple, df_horario[["estacion_id", "fecha"]].drop_duplicates().values))
    dias_h_previos = set()
    if not df_diario.empty:
        dias_h_previos = (
            set(
                ResumenDiario.objects.filter(
                    origen="H",
                    estacion_id__in=df_diario["estacion_id"].unique().tolist(),
                    fecha__in=df_diario["fecha"].unique().tolist(),
                ).values_list("estacion_id", "fecha")
            )
            - dias_h
        )

    registros = []

    # Diarios
    df_diario = df_diario.drop_duplicates(subset=["estacion_id", "fecha"], keep="last")
    for _, row in df_diario.iterrows():
        if (row["estacion_id"], row["fecha"]) in dias_h_previos:
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
                humedad_media=_num(row.get("humedad_media")),
                radiacion_maxima=_num(row.get("radiacion_maxima")),
                viento_maximo=_num(row.get("viento_maximo")),
                corregido_a_mano=bool(manuales.get((row["estacion_id"], row["fecha"]), False)),
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

            # La lluvia observada no depende de que haya temperaturas ese día.
            precipitacion = (
                _num(grupo["precipitacion"].sum(min_count=1)) if "precipitacion" in grupo else None
            )
            tmax = _num(_serie_temp(grupo, "temperatura_maxima").max())
            tmin = _num(_serie_temp(grupo, "temperatura_minima").min())
            tmedia = _num(serie_tmedia.mean())
            amplitud = round(tmax - tmin, 2) if tmax is not None and tmin is not None else None
            es_confiable = horas_validas >= config.horas_minimas_dia
            if tmax is None and tmin is None and tmedia is None:
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
                    humedad_media=_num(grupo["humedad_media"].mean()),
                    radiacion_maxima=_num(grupo["radiacion_maxima"].max()),
                    viento_maximo=_num(grupo["viento_maximo"].max()),
                    corregido_a_mano=bool(manuales.get((est_id, fecha), False)),
                    origen="H",
                    horas_validas=horas_validas,
                    horas_esperadas=esperadas,
                    confiable=es_confiable,
                    motivo_nulo=motivo,
                )
            )

    grupos = df.groupby(["estacion_id", "fecha", "frecuencia"])
    invalidas = {}
    for registro in registros:
        grupo = grupos.get_group((registro.estacion_id, registro.fecha, registro.origen))
        afectadas = {
            destino
            for variable, destino in VARIABLES_RESUMEN.items()
            if grupo[f"{variable}_fuera_de_rango"].any()
        }
        # Una temperatura horaria inválida impide el resumen térmico completo.
        if registro.origen == "H" and "tmedia" in afectadas:
            afectadas.update(("tmax", "tmin"))
        invalidas[(registro.estacion_id, registro.fecha, registro.origen)] = afectadas
        if afectadas:
            for campo in afectadas:
                setattr(registro, campo, None)
            if afectadas.intersection(("tmax", "tmin")):
                registro.amplitud_termica = None
            registro.motivo_nulo = MOTIVO_RANGO
            if afectadas.intersection(("tmax", "tmin", "tmedia")):
                registro.confiable = False
        if any(grupo[f"{variable}_excluido"].any() for variable in VARIABLES_RESUMEN):
            registro.motivo_nulo = (
                f"{MOTIVO_RANGO}; {MOTIVO_EXCLUIDO}" if afectadas else MOTIVO_EXCLUIDO
            )

    # La prioridad horaria es por variable: cargar solo humedad horaria no
    # oculta temperaturas diarias observadas. Un valor horario fuera de rango
    # conserva la invalidación de E1C-71 y no se sustituye con el dato diario.
    por_dia = {}
    termicas = ("tmax", "tmin", "tmedia")
    for registro in registros:
        clave = (registro.estacion_id, registro.fecha)
        diario = por_dia.get(clave)
        if diario is not None:
            termica_horaria = any(getattr(registro, campo) is not None for campo in termicas)
            bloqueadas = invalidas[(*clave, "H")]
            for campo in VARIABLES_RESUMEN.values():
                if getattr(registro, campo) is None and campo not in bloqueadas:
                    setattr(registro, campo, getattr(diario, campo))
            registro.amplitud_termica = (
                round(registro.tmax - registro.tmin, 2)
                if registro.tmax is not None and registro.tmin is not None
                else None
            )
            if not termica_horaria and any(
                getattr(registro, campo) is not None for campo in termicas
            ):
                registro.origen = "D"
                registro.horas_validas = registro.horas_esperadas = None
                registro.confiable = diario.confiable and not bloqueadas.intersection(termicas)
            motivos = [registro.motivo_nulo, diario.motivo_nulo]
            persistentes = [
                motivo
                for motivo in (MOTIVO_RANGO, MOTIVO_EXCLUIDO)
                if any(motivo in (texto or "") for texto in motivos)
            ]
            registro.motivo_nulo = "; ".join(persistentes) or (
                None
                if any(getattr(registro, campo) is not None for campo in termicas)
                else registro.motivo_nulo
            )
        por_dia[clave] = registro
    registros = list(por_dia.values())

    ResumenDiario.objects.bulk_create(
        registros,
        update_conflicts=True,
        unique_fields=["estacion", "fecha"],
        update_fields=campos_update,
    )
    return registros


# Funciones del contrato JSON


def resumen_diario(estacion: Estacion, desde: str, hasta: str) -> dict:
    dias = ResumenDiario.objects.filter(estacion=estacion, fecha__range=[desde, hasta]).order_by(
        "fecha"
    )
    data = {"estacion_id": estacion.codigo, "desde": desde, "hasta": hasta, "dias": []}

    for d in dias:
        dia_dict = {
            "fecha": d.fecha.strftime("%Y-%m-%d"),
            "tmax": d.tmax,
            "tmin": d.tmin,
            "tmedia": d.tmedia,
            "amplitud": d.amplitud_termica,
            "precipitacion": d.precipitacion,
            "humedad_media": d.humedad_media,
            "radiacion_maxima": d.radiacion_maxima,
            "viento_maximo": d.viento_maximo,
            "corregido_a_mano": d.corregido_a_mano,
        }
        if d.motivo_nulo:
            dia_dict["motivo_nulo"] = d.motivo_nulo
        data["dias"].append(dia_dict)
    return data


def completitud_por_temporada(estacion: Estacion | None = None) -> list[dict]:
    qs = ResumenDiario.objects.filter(estacion__activa=True)

    if estacion is not None:
        qs = qs.filter(estacion=estacion)

    umbral = ConfiguracionCalidad.obtener_umbral()
    hoy = timezone.localdate()

    filas = (
        qs.values("estacion__codigo", "temporada")
        .annotate(
            n_tmax=Count("tmax"),
            n_tmin=Count("tmin"),
            n_tmedia=Count("tmedia"),
            n_precipitacion=Count("precipitacion"),
            n_humedad_media=Count("humedad_media"),
            n_radiacion_maxima=Count("radiacion_maxima"),
            n_viento_maximo=Count("viento_maximo"),
        )
        .order_by("estacion__codigo", "temporada")
    )

    resultado = []
    for f in filas:
        inicio, fin = rango_temporada(f["temporada"])
        fin = min(fin, hoy)
        total = max((fin - inicio).days + 1, 1)

        def pct(n, total=total):
            return round(min(n / total * 100, 100), 1)

        variables = {
            "tmax": pct(f["n_tmax"]),
            "tmin": pct(f["n_tmin"]),
            "tmedia": pct(f["n_tmedia"]),
            "precipitacion": pct(f["n_precipitacion"]),
            "humedad_media": pct(f["n_humedad_media"]),
            "radiacion_maxima": pct(f["n_radiacion_maxima"]),
            "viento_maximo": pct(f["n_viento_maximo"]),
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
        ResumenDiario.objects.filter(
            HAY_INFORMACION,
            estacion__activa=True,
        )
        .order_by("temporada")
        .values_list("temporada", flat=True)
        .distinct()
    )


def estaciones(incluir_inactivas: bool = False) -> list[dict]:
    umbral = ConfiguracionCalidad.obtener_umbral()
    resultado = []

    qs_estaciones = Estacion.objects.order_by("nombre")

    if not incluir_inactivas:
        qs_estaciones = qs_estaciones.filter(activa=True)

    for est in qs_estaciones:
        qs = ResumenDiario.objects.filter(estacion=est)

        agg = qs.filter(HAY_INFORMACION).aggregate(
            inicio=Min("fecha"),
            fin=Max("fecha"),
            n_completos=Count(
                "id",
                filter=Q(tmax__isnull=False, tmin__isnull=False),
            ),
            n_tmax=Count("tmax"),
            n_tmin=Count("tmin"),
            n_tmedia=Count("tmedia"),
            n_precipitacion=Count("precipitacion"),
            n_humedad_media=Count("humedad_media"),
            n_radiacion_maxima=Count("radiacion_maxima"),
            n_viento_maximo=Count("viento_maximo"),
        )

        variables = [
            nombre
            for nombre, n in [
                ("tmax", agg["n_tmax"]),
                ("tmin", agg["n_tmin"]),
                ("tmedia", agg["n_tmedia"]),
                ("precipitacion", agg["n_precipitacion"]),
                ("humedad_media", agg["n_humedad_media"]),
                ("radiacion_maxima", agg["n_radiacion_maxima"]),
                ("viento_maximo", agg["n_viento_maximo"]),
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

        n_temporadas = qs.filter(HAY_INFORMACION).order_by().values("temporada").distinct().count()

        resultado.append(
            {
                "id": est.codigo,
                "nombre": est.nombre,
                "subzona": est.subzona,
                "propietario": est.propietario,
                "latitud": est.latitud,
                "longitud": est.longitud,
                "variables": variables,
                "fecha_inicio": (agg["inicio"].isoformat() if agg["inicio"] else None),
                "fecha_fin": (agg["fin"].isoformat() if agg["fin"] else None),
                "temporadas_disponibles": n_temporadas,
                "calidad_dato": {
                    "completitud_pct": completitud,
                    "confiable": (completitud is not None and completitud >= umbral),
                    "umbral_completitud_pct": umbral,
                    "resolucion_origen": resolucion,
                    "version_calculo": None,
                },
                "tipo": est.tipo,
            }
        )

    return resultado
