import pandas as pd
from django.db.models import Count, Sum

from apps.clima.models import ConfiguracionCalidad, Estacion, MedicionHoraria, ResumenDiario
from apps.clima.services import TZ
from apps.clima.temporadas import rango_invernal

# Horas secas seguidas que separan un evento de otro (HAY QUE CONFIRMAR CON EL ENOLOGO).
SEPARACION_HORAS_EVENTO = 6
# Minimo de temporadas confiables para que el "promedio histórico" tenga sentido.
MIN_TEMPORADAS_PROMEDIO = 2


# Acumulado invernal por temporada


def _acumulado_invernal(estacion: Estacion, temporada: str, umbral: float, hoy) -> dict:
    ini, fin = rango_invernal(temporada)
    # Se filtra por fecha y no por la columna `temporada`: esa columna parte en julio,
    # mayo-junio caen en la temporada anterior.
    agg = ResumenDiario.objects.filter(estacion=estacion, fecha__range=[ini, fin]).aggregate(
        total=Sum("precipitacion"), n=Count("precipitacion")
    )
    n_dias, total = agg["n"], agg["total"]

    fin_efectivo = min(fin, hoy)  # invierno en curso: se espera hasta hoy
    esperados = max((fin_efectivo - ini).days + 1, 0)
    completitud = round(min(n_dias / esperados * 100, 100), 1) if esperados else None
    confiable = completitud is not None and completitud >= umbral

    item = {
        "estacion_id": estacion.codigo,
        "temporada": temporada,
        "periodo": {"desde": ini.isoformat(), "hasta": fin.isoformat()},
        "acumulado_mm": round(total, 1) if total is not None else None,
        "dias_con_dato": n_dias,
        "dias_esperados": esperados,
        "completitud_pct": completitud,
        "confiable": confiable,
        "en_curso": fin > hoy,
    }
    if n_dias == 0:
        item["observacion"] = "sin datos de precipitación en el período invernal"
    elif not confiable:
        item["observacion"] = "acumulado parcial: la completitud no alcanza el umbral"
    return item


def lluvia_invernal(estacion_codigo: str, temporada: str) -> dict:
    estacion = Estacion.objects.get(codigo=estacion_codigo)  # error si no existe
    hoy = pd.Timestamp.now(tz=TZ).date()
    return _acumulado_invernal(estacion, temporada, ConfiguracionCalidad.obtener_umbral(), hoy)


# Eventos de lluvia: mm/h máximos, duración y total diario


def eventos_lluvia(
    estacion_codigo: str, desde, hasta, separacion_horas: int = SEPARACION_HORAS_EVENTO
) -> dict:
    estacion = Estacion.objects.get(codigo=estacion_codigo)
    inicio_rango = pd.Timestamp(desde, tz=TZ)
    fin_rango = pd.Timestamp(hasta, tz=TZ) + pd.DateOffset(days=1)  # incluye el día "hasta"

    data = {
        "estacion_id": estacion_codigo,
        "desde": str(desde),
        "hasta": str(hasta),
        "separacion_horas": separacion_horas,
        "eventos": [],
    }

    filas = list(
        MedicionHoraria.objects.filter(
            estacion=estacion,
            frecuencia="H",
            variable="precipitacion",
            timestamp__gte=inicio_rango.to_pydatetime(),
            timestamp__lt=fin_rango.to_pydatetime(),
        )
        .order_by("timestamp")
        .values_list("timestamp", "valor")
    )
    if not filas:
        data["observacion"] = "sin datos horarios de precipitación en el rango"
        return data

    serie = pd.DataFrame(filas, columns=["timestamp", "valor"])
    serie["timestamp"] = pd.to_datetime(serie["timestamp"], utc=True).dt.tz_convert(TZ)
    serie["fecha"] = serie["timestamp"].dt.date
    total_dia = serie.groupby("fecha")["valor"].sum(min_count=1)

    lluvia = serie[serie["valor"] > 0].copy()  # los nulos y los 0 no son lluvia
    if lluvia.empty:
        data["observacion"] = "sin lluvia en el rango"
        return data

    # Una hora lluviosa abre un evento nuevo si pasaron más de `separacion_horas` desde la anterior
    horas_desde_anterior = lluvia["timestamp"].diff().dt.total_seconds() / 3600
    lluvia["evento"] = (
        horas_desde_anterior.isna() | (horas_desde_anterior > separacion_horas)
    ).cumsum()

    for _, g in lluvia.groupby("evento"):
        primera, ultima = g["timestamp"].iloc[0], g["timestamp"].iloc[-1]
        duracion = (ultima - primera) / pd.Timedelta(hours=1) + 1  # incluye la última hora
        data["eventos"].append(
            {
                "inicio": primera.isoformat(),
                "fin": ultima.isoformat(),
                "duracion_horas": round(duracion, 1),
                "horas_con_lluvia": len(g),
                "total_mm": round(g["valor"].sum(), 1),
                "intensidad_max_mm_h": round(g["valor"].max(), 1),
                "dias": [
                    {"fecha": d.isoformat(), "total_dia_mm": round(total_dia[d], 1)}
                    for d in sorted(g["fecha"].unique())
                ],
            }
        )
    return data


# Comparación contra el promedio histórico


def comparar_lluvia_invernal(estacion_codigo: str, temporadas: list[str] | None = None) -> dict:
    estacion = Estacion.objects.get(codigo=estacion_codigo)
    umbral = ConfiguracionCalidad.obtener_umbral()
    hoy = pd.Timestamp.now(tz=TZ).date()

    anios = ResumenDiario.objects.filter(estacion=estacion, precipitacion__isnull=False).dates(
        "fecha", "year"
    )
    todas = []
    for anio in sorted({a.year for a in anios}):
        item = _acumulado_invernal(estacion, f"{anio}-{anio + 1}", umbral, hoy)
        if item["dias_con_dato"] > 0:
            todas.append(item)

    # El promedio usa solo inviernos terminados y confiables
    base = [i["acumulado_mm"] for i in todas if i["confiable"] and not i["en_curso"]]
    promedio = round(sum(base) / len(base), 1) if len(base) >= MIN_TEMPORADAS_PROMEDIO else None

    resultado = {
        "estacion_id": estacion_codigo,
        "promedio_historico_mm": promedio,
        "temporadas_en_promedio": len(base),
        "temporadas": [],
    }
    if promedio is None:
        resultado["observacion"] = (
            f"se necesitan al menos {MIN_TEMPORADAS_PROMEDIO} inviernos confiables para el promedio"
        )

    for item in todas:
        if temporadas and item["temporada"] not in temporadas:
            continue
        diferencia = pct = None
        if promedio is not None and item["acumulado_mm"] is not None:
            diferencia = round(item["acumulado_mm"] - promedio, 1)
            pct = round(diferencia / promedio * 100, 1) if promedio else None
        resultado["temporadas"].append(
            {
                "temporada": item["temporada"],
                "acumulado_mm": item["acumulado_mm"],
                "completitud_pct": item["completitud_pct"],
                "confiable": item["confiable"],
                "en_curso": item["en_curso"],
                "diferencia_mm": diferencia,
                "diferencia_pct": pct,
            }
        )
    return resultado
