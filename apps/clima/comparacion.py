from datetime import date

import pandas as pd
from django.db.models import Max, Min, Q
from django.utils import timezone

from apps.clima.metricas import METRICAS as METRICAS
from apps.clima.metricas import valor_metrica as valor_metrica
from apps.clima.models import ConfiguracionCalidad, Estacion, ResumenDiario

# Variables de temperatura que se comparan entre estaciones.
VARIABLES_TERMICAS = ("tmedia", "tmax", "tmin")


# Métricas por temporada


def _trasladar(fecha: date, ini_origen: date, ini_destino: date) -> date:
    """La misma fecha calendario en otra temporada (el 29 de febrero pasa al 28)."""
    anio = ini_destino.year + (fecha.year - ini_origen.year)
    try:
        return date(anio, fecha.month, fecha.day)
    except ValueError:
        return date(anio, fecha.month, 28)


def cortes(metrica: str, temporadas: list[str], hoy: date) -> tuple[dict[str, date], str]:
    """Fecha hasta la que se acumula cada temporada.

    Si todas terminaron, se usa la temporada completa. Si alguna sigue en curso, todas se
    cortan en el mismo día calendario que alcanzó la más atrasada (acumulado al mismo día).
    """
    ventana = METRICAS[metrica][1]
    ventanas = {t: ventana(t) for t in temporadas}
    if not any(fin > hoy for _, fin in ventanas.values()):
        return {t: fin for t, (_, fin) in ventanas.items()}, "completa"

    ini0 = ventanas[temporadas[0]][0]
    corte0 = min(_trasladar(min(fin, hoy), ini, ini0) for ini, fin in ventanas.values())
    return {t: _trasladar(corte0, ini0, ini) for t, (ini, _) in ventanas.items()}, "al_mismo_dia"


# E1C-50: comparar temporadas


def comparar_temporadas(
    estacion: Estacion, temporada: str, referencia: str, hoy: date | None = None
) -> dict:
    """Diferencia (temporada - referencia) de cada índice y métrica."""
    hoy = hoy or timezone.localdate()
    umbral = ConfiguracionCalidad.obtener_umbral()

    metricas = []
    for nombre, (unidad, _, _) in METRICAS.items():
        fechas, modo = cortes(nombre, [temporada, referencia], hoy)
        a = valor_metrica(estacion, nombre, temporada, fechas[temporada], umbral)
        b = valor_metrica(estacion, nombre, referencia, fechas[referencia], umbral)
        item = {
            "metrica": nombre,
            "unidad": unidad,
            "modo": modo,
            "temporada": a,
            "referencia": b,
            "comparable": a["confiable"] and b["confiable"],
            "diferencia": None,
            "diferencia_pct": None,
        }
        if item["comparable"]:
            item["diferencia"] = round(a["valor"] - b["valor"], 1)
            if b["valor"]:
                item["diferencia_pct"] = round(item["diferencia"] / b["valor"] * 100, 1)
        else:
            faltan = [
                nombre_t for nombre_t, x in ((temporada, a), (referencia, b)) if not x["confiable"]
            ]
            item["observacion"] = f"datos insuficientes en: {', '.join(faltan)}"
        metricas.append(item)
    return {
        "estacion_id": estacion.codigo,
        "temporada": temporada,
        "referencia": referencia,
        "metricas": metricas,
    }


def temporadas_con_datos(estacion: Estacion) -> list[str]:
    """Etiquetas AAAA-BBBB de la estación, de la más antigua a la más reciente."""
    anios = set()
    for f in ResumenDiario.objects.filter(estacion=estacion).dates("fecha", "year"):
        anios.update((f.year - 1, f.year))
    return [f"{a}-{a + 1}" for a in sorted(anios)]


def comparar_con_anteriores(estacion: Estacion, temporada: str, hoy: date | None = None) -> dict:
    """La temporada frente a cada temporada anterior que tenga datos."""
    hoy = hoy or timezone.localdate()
    anteriores = [t for t in temporadas_con_datos(estacion) if t < temporada]
    comparaciones = [comparar_temporadas(estacion, temporada, t, hoy) for t in anteriores]
    return {
        "estacion_id": estacion.codigo,
        "temporada": temporada,
        # Se omiten las temporadas anteriores sin ningún dato en ninguna métrica.
        "comparaciones": [
            c
            for c in comparaciones
            if any(m["referencia"]["dias_con_dato"] > 0 for m in c["metricas"])
        ],
    }


# E1C-51: comparar estaciones


def _rango_comun(a: Estacion, b: Estacion) -> tuple[date, date] | None:
    hay_temperatura = Q(tmax__isnull=False) | Q(tmin__isnull=False) | Q(tmedia__isnull=False)
    rangos = []
    for est in (a, b):
        r = ResumenDiario.objects.filter(hay_temperatura, estacion=est).aggregate(
            ini=Min("fecha"), fin=Max("fecha")
        )
        if r["ini"] is None:
            return None
        rangos.append(r)
    ini = max(r["ini"] for r in rangos)
    fin = min(r["fin"] for r in rangos)
    return (ini, fin) if ini <= fin else None


def comparar_estaciones(
    a: Estacion, b: Estacion, desde: date | None = None, hasta: date | None = None
) -> dict:
    """Diferencia de temperatura (A - B) en los días en que ambas estaciones tienen dato.

    Sin `desde`/`hasta` usa el período en que las dos tienen datos.
    """
    if a == b:
        raise ValueError("Elige dos estaciones distintas.")
    umbral = ConfiguracionCalidad.obtener_umbral()

    if desde is None or hasta is None:
        comun = _rango_comun(a, b)
        if comun is None:
            return {
                "estacion_a": a.codigo,
                "estacion_b": b.codigo,
                "periodo": None,
                "variables": {},
                "observacion": "las estaciones no comparten período con datos de temperatura",
            }
        desde, hasta = desde or comun[0], hasta or comun[1]
    if desde > hasta:
        raise ValueError("`desde` no puede ser posterior a `hasta`.")
    dias_periodo = (hasta - desde).days + 1

    filas = ResumenDiario.objects.filter(estacion__in=(a, b), fecha__range=(desde, hasta)).values(
        "estacion_id", "fecha", *VARIABLES_TERMICAS
    )
    df = pd.DataFrame(list(filas), columns=["estacion_id", "fecha", *VARIABLES_TERMICAS])
    ancho = df[df["estacion_id"] == a.pk].merge(
        df[df["estacion_id"] == b.pk], on="fecha", suffixes=("_a", "_b")
    )

    variables = {}
    for var in VARIABLES_TERMICAS:
        pares = ancho[[f"{var}_a", f"{var}_b"]].dropna()
        n = len(pares)
        completitud = round(n / dias_periodo * 100, 1)
        item = {
            "dias_comunes": n,
            "completitud_pct": completitud,
            "confiable": n > 0 and completitud >= umbral,
            "diferencia_media_c": None,
            "desviacion_c": None,
            "dias_a_mas_calida_pct": None,
        }
        if n:
            dif = pares[f"{var}_a"] - pares[f"{var}_b"]
            item["diferencia_media_c"] = round(float(dif.mean()), 2)
            item["desviacion_c"] = round(float(dif.std()), 2) if n > 1 else None
            item["dias_a_mas_calida_pct"] = round(float((dif > 0).mean() * 100), 1)
        else:
            item["observacion"] = "sin días con dato en ambas estaciones"
        variables[var] = item
    return {
        "estacion_a": a.codigo,
        "estacion_b": b.codigo,
        "periodo": {"desde": desde.isoformat(), "hasta": hasta.isoformat()},
        "dias_en_periodo": dias_periodo,
        "variables": variables,
    }
