import pandas as pd
from django.utils import timezone

from apps.clima.metricas import valor_metrica
from apps.clima.models import ConfiguracionCalidad, Estacion, MedicionHoraria, ResumenDiario
from apps.clima.temporadas import MIN_TEMPORADAS_PROMEDIO, rango_invernal

# Horas secas seguidas que separan un evento de otro (HAY QUE CONFIRMAR CON EL ENOLOGO).
SEPARACION_HORAS_EVENTO = 6
# Acumulado invernal por temporada


def _acumulado_invernal(estacion: Estacion, temporada: str, umbral: float, hoy) -> dict:
    ini, fin = rango_invernal(temporada)
    medicion = valor_metrica(estacion, "lluvia_invernal", temporada, hoy, umbral)
    n_dias, total = medicion["dias_con_dato"], medicion["valor"]
    esperados = medicion["dias_esperados"]
    completitud = medicion["completitud_pct"]
    confiable = medicion["confiable"]

    item = {
        "estacion_id": estacion.codigo,
        "temporada": temporada,
        "periodo": {"desde": ini.isoformat(), "hasta": fin.isoformat()},
        "acumulado_mm": total,
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


def lluvia_invernal(estacion: Estacion, temporada: str) -> dict:
    hoy = timezone.localdate()
    return _acumulado_invernal(estacion, temporada, ConfiguracionCalidad.obtener_umbral(), hoy)


# Eventos de lluvia: mm/h máximos, duración y total diario


def eventos_lluvia(
    estacion: Estacion, desde, hasta, separacion_horas: int = SEPARACION_HORAS_EVENTO
) -> dict:
    tz = timezone.get_current_timezone_name()
    inicio_rango = pd.Timestamp(desde).tz_localize(tz, nonexistent="shift_forward")
    fin_rango = (pd.Timestamp(hasta) + pd.Timedelta(days=1)).tz_localize(
        tz, nonexistent="shift_forward"
    )  # incluye el día "hasta"

    data = {
        "estacion_id": estacion.codigo,
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
    serie["timestamp"] = pd.to_datetime(serie["timestamp"], utc=True).dt.tz_convert(tz)
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
        en_evento = serie[(serie["timestamp"] >= primera) & (serie["timestamp"] <= ultima)]
        horas_sin_dato = int(round(duracion)) - int(en_evento["valor"].notna().sum())
        data["eventos"].append(
            {
                "inicio": primera.isoformat(),
                "fin": ultima.isoformat(),
                "duracion_horas": round(duracion, 1),
                "horas_con_lluvia": len(g),
                "horas_sin_dato": horas_sin_dato,
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


def comparar_lluvia_invernal(estacion: Estacion, temporadas: list[str] | None = None) -> dict:
    umbral = ConfiguracionCalidad.obtener_umbral()
    hoy = timezone.localdate()

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
        "estacion_id": estacion.codigo,
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
        if (
            promedio is not None
            and item["acumulado_mm"] is not None
            and item["confiable"]
            and not item["en_curso"]
        ):
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
