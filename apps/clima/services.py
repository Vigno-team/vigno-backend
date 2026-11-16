import pandas as pd
from django.utils import timezone

from apps.clima.calidad import MOTIVO_EXCLUIDO
from apps.clima.models import ConfiguracionCalidad, ResumenDiario
from apps.clima.rangos import MOTIVO_RANGO, VARIABLES
from apps.clima.resultados import (
    HAY_DATO as HAY_DATO,
)
from apps.clima.resultados import (
    HAY_INFORMACION as HAY_INFORMACION,
)
from apps.clima.resultados import (
    completitud_por_temporada as completitud_por_temporada,
)
from apps.clima.resultados import (
    estaciones as estaciones,
)
from apps.clima.resultados import (
    resumen_diario as resumen_diario,
)
from apps.clima.resultados import (
    temporadas as temporadas,
)
from apps.clima.temporadas import temporada_de

VARIABLES_RESUMEN = {
    **VARIABLES,
    "humedad_media": "humedad_media",
    "radiacion_maxima": "radiacion_maxima",
    "viento_maximo": "viento_maximo",
}


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
