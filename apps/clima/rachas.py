from datetime import date, timedelta
from typing import Any

from apps.clima.models import Estacion, ResumenDiario
from apps.clima.temporadas import rango_temporada

UN_DIA = timedelta(days=1)


def identificar_rachas(
    estacion: Estacion, temporada: str, umbral_temp: float = 35.0, min_dias: int = 5
) -> list[dict[str, Any]]:
    """
    Identifica secuencias de días consecutivos en los que la temperatura
    máxima supera o iguala el umbral dado.

    Una racha queda interrumpida por dato faltante si el día anterior a su
    inicio o el siguiente a su fin no tiene tmax.
    """
    try:
        umbral_temp = float(umbral_temp)
        min_dias = int(min_dias)
    except (ValueError, TypeError) as e:
        raise ValueError("Los parámetros umbral_temp y min_dias deben ser numéricos.") from e

    if min_dias <= 0:
        raise ValueError("min_dias debe ser mayor a 0.")

    dias = list(
        ResumenDiario.objects.filter(estacion=estacion, temporada=temporada).order_by("fecha")
    )

    if not dias:
        return []

    # Fechas con tmax registrado: un día sin registro o con tmax nulo es dato faltante.
    con_dato = {d.fecha for d in dias if d.tmax is not None}

    # Solo se revisan días dentro de la temporada, ampliada si hay registros
    # guardados fuera de su rango (por ejemplo, ingestados con --temporada).
    inicio_temp, fin_temp = rango_temporada(temporada)
    primer_dia = min(inicio_temp, dias[0].fecha)
    ultimo_dia = max(fin_temp, dias[-1].fecha)

    def falta_dato(fecha: date) -> bool:
        return primer_dia <= fecha <= ultimo_dia and fecha not in con_dato

    # Agrupa los días calurosos de fechas consecutivas.
    calurosos = [d for d in dias if d.tmax is not None and d.tmax >= umbral_temp]
    grupos: list[list[ResumenDiario]] = []
    for d in calurosos:
        if grupos and (d.fecha - grupos[-1][-1].fecha).days == 1:
            grupos[-1].append(d)
        else:
            grupos.append([d])

    rachas = []
    for grupo in grupos:
        inicio, fin = grupo[0].fecha, grupo[-1].fecha
        interrumpida = falta_dato(inicio - UN_DIA) or falta_dato(fin + UN_DIA)
        rachas.append(
            {
                "inicio": inicio,
                "fin": fin,
                "dias": len(grupo),
                "tmax_maxima": max(d.tmax for d in grupo),
                "interrumpida_por_dato_faltante": interrumpida,
                "con_incidencia": len(grupo) >= min_dias,
            }
        )

    return rachas
