from datetime import date

from apps.clima.comparacion import (
    METRICAS,
    cortes,
    hoy_en_chile,
    temporadas_con_datos,
    valor_metrica,
)
from apps.clima.models import ConfiguracionCalidad, Estacion

# Cortes provisionales: CONFIRMAR con el enólogo. Están aquí para cambiarlos en un solo lugar.
UMBRAL_TERMICA_PCT = 5.0
UMBRAL_HIDRICA_PCT = 20.0
MIN_TEMPORADAS_BASE = 2

METRICA_TERMICA = "winkler"
METRICA_HIDRICA = "lluvia_invernal"

ETIQUETAS_TERMICA = ("fria", "normal", "calida")  # (bajo, medio, alto)
ETIQUETAS_HIDRICA = ("seca", "normal", "lluviosa")


def _etiqueta(diferencia_pct: float, umbral_pct: float, etiquetas: tuple[str, str, str]) -> str:
    bajo, medio, alto = etiquetas
    if diferencia_pct >= umbral_pct:
        return alto
    if diferencia_pct <= -umbral_pct:
        return bajo
    return medio


def _eje(estacion, metrica, temporada, hoy, umbral, umbral_pct, etiquetas) -> dict:
    """Valor de la temporada, promedio de las demás y etiqueta de un eje."""
    detalle = {
        "metrica": metrica,
        "umbral_pct": umbral_pct,
        "valor": None,
        "promedio_historico": None,
        "diferencia_pct": None,
        "temporadas_en_promedio": 0,
        "modo": None,
        "etiqueta": None,
    }
    candidatas = temporadas_con_datos(estacion)
    fechas, modo = cortes(metrica, [temporada], hoy)
    detalle["modo"] = modo

    propia = valor_metrica(estacion, metrica, temporada, fechas[temporada], umbral)
    detalle["valor"] = propia["valor"]
    if not propia["confiable"]:
        detalle["observacion"] = "la temporada no tiene datos suficientes para este eje"
        return detalle

    base = []
    for otra in candidatas:
        if modo == "completa":
            if not _termino(metrica, otra, hoy):
                continue  # solo temporadas terminadas
            corte = METRICAS[metrica][1](otra)[1]
        else:
            if otra == temporada:
                continue  # una temporada incompleta no entra en su propio promedio
            corte = cortes(metrica, [temporada, otra], hoy)[0][otra]  # mismo día calendario
        item = valor_metrica(estacion, metrica, otra, corte, umbral)
        if item["confiable"]:
            base.append(item["valor"])
    detalle["temporadas_en_promedio"] = len(base)
    if len(base) < MIN_TEMPORADAS_BASE:
        detalle["observacion"] = (
            f"se necesitan al menos {MIN_TEMPORADAS_BASE} temporadas confiables para el promedio"
        )
        return detalle

    promedio = round(sum(base) / len(base), 1)
    detalle["promedio_historico"] = promedio
    if promedio:
        detalle["diferencia_pct"] = round((propia["valor"] - promedio) / promedio * 100, 1)
        detalle["etiqueta"] = _etiqueta(detalle["diferencia_pct"], umbral_pct, etiquetas)
    else:
        detalle["observacion"] = "el promedio histórico es 0; no se puede calcular el porcentaje"
    return detalle


def _termino(metrica: str, temporada: str, hoy: date) -> bool:
    return METRICAS[metrica][1](temporada)[1] <= hoy


def clasificar_temporada(estacion_codigo: str, temporada: str, hoy: date | None = None) -> dict:
    estacion = Estacion.objects.get(codigo=estacion_codigo)  # error si no existe
    hoy = hoy or hoy_en_chile()
    umbral = ConfiguracionCalidad.obtener_umbral()

    termica = _eje(
        estacion,
        METRICA_TERMICA,
        temporada,
        hoy,
        umbral,
        UMBRAL_TERMICA_PCT,
        ETIQUETAS_TERMICA,
    )
    hidrica = _eje(
        estacion,
        METRICA_HIDRICA,
        temporada,
        hoy,
        umbral,
        UMBRAL_HIDRICA_PCT,
        ETIQUETAS_HIDRICA,
    )
    return {
        "estacion_id": estacion_codigo,
        "temporada": temporada,
        "termica": termica["etiqueta"],
        "hidrica": hidrica["etiqueta"],
        "criterio": (
            f"Térmica: índice Winkler frente al promedio de la estación, "
            f"cálida si la diferencia es >= +{UMBRAL_TERMICA_PCT:g} % y fría si es "
            f"<= -{UMBRAL_TERMICA_PCT:g} %. "
            f"Hídrica: lluvia invernal (mayo-agosto) frente al promedio de la estación, "
            f"lluviosa si la diferencia es >= +{UMBRAL_HIDRICA_PCT:g} % y seca si es "
            f"<= -{UMBRAL_HIDRICA_PCT:g} %. En otro caso, normal."
        ),
        "detalle": {"termica": termica, "hidrica": hidrica},
    }
