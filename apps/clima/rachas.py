from typing import Any

from apps.clima.models import Estacion, ResumenDiario
from apps.clima.temporadas import rango_de


def identificar_rachas(
    estacion: Estacion, temporada: str, umbral_temp: float = 35.0, min_dias: int = 5
) -> list[dict[str, Any]]:
    """
    Identifica secuencias de días consecutivos en los que la temperatura
    máxima supera o iguala el umbral dado.
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

    rachas = []
    racha_actual = None
    prev_d = None

    inicio_temp, fin_temp = rango_de(temporada)

    for d in dias:
        if d.tmax is not None and d.tmax >= umbral_temp:
            if racha_actual is None:
                interrumpida = False
                if prev_d is None:
                    # Si es el primer día en la BD pero no el primero de la temporada
                    if d.fecha > inicio_temp:
                        interrumpida = True
                else:
                    # Si el día anterior no existe o su tmax es nulo
                    if (d.fecha - prev_d.fecha).days > 1 or prev_d.tmax is None:
                        interrumpida = True

                racha_actual = {
                    "inicio": d.fecha,
                    "fin": d.fecha,
                    "dias": 1,
                    "tmax_maxima": d.tmax,
                    "interrumpida_por_dato_faltante": interrumpida,
                }
            else:
                if (d.fecha - racha_actual["fin"]).days == 1:
                    racha_actual["fin"] = d.fecha
                    racha_actual["dias"] += 1
                    racha_actual["tmax_maxima"] = max(racha_actual["tmax_maxima"], d.tmax)
                else:
                    racha_actual["con_incidencia"] = racha_actual["dias"] >= min_dias
                    racha_actual["interrumpida_por_dato_faltante"] = True
                    rachas.append(racha_actual)

                    racha_actual = {
                        "inicio": d.fecha,
                        "fin": d.fecha,
                        "dias": 1,
                        "tmax_maxima": d.tmax,
                        "interrumpida_por_dato_faltante": True,
                    }
        else:
            if racha_actual is not None:
                if (d.fecha - racha_actual["fin"]).days > 1:
                    racha_actual["interrumpida_por_dato_faltante"] = True
                elif d.tmax is None:
                    racha_actual["interrumpida_por_dato_faltante"] = True

                racha_actual["con_incidencia"] = racha_actual["dias"] >= min_dias
                rachas.append(racha_actual)
                racha_actual = None

        prev_d = d

    if racha_actual is not None:
        if racha_actual["fin"] < fin_temp:
            racha_actual["interrumpida_por_dato_faltante"] = True

        racha_actual["con_incidencia"] = racha_actual["dias"] >= min_dias
        rachas.append(racha_actual)

    return rachas
