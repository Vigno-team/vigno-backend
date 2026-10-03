from typing import Any

from apps.clima.models import Estacion, ResumenDiario


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
        if min_dias < 1:
            min_dias = 1
    except (ValueError, TypeError):
        umbral_temp = 35.0
        min_dias = 5

    dias = ResumenDiario.objects.filter(estacion=estacion, temporada=temporada).order_by("fecha")

    if not dias.exists():
        return []

    rachas = []
    racha_actual = None

    for d in dias:
        # Se requiere tener dato de tmax y que sea >= umbral (Ej: 35.0)
        if d.tmax is not None and d.tmax >= umbral_temp:
            if racha_actual is None:
                racha_actual = {
                    "inicio": d.fecha,
                    "fin": d.fecha,
                    "duracion": 1,
                    "interrumpida_por_dato_faltante": False,
                }
            else:
                if (d.fecha - racha_actual["fin"]).days == 1:
                    racha_actual["fin"] = d.fecha
                    racha_actual["duracion"] += 1
                else:
                    # Racha cortada por un salto físico en la base de datos
                    racha_actual["incidencia"] = racha_actual["duracion"] >= min_dias
                    racha_actual["interrumpida_por_dato_faltante"] = True
                    rachas.append(racha_actual)
                    racha_actual = {
                        "inicio": d.fecha,
                        "fin": d.fecha,
                        "duracion": 1,
                        "interrumpida_por_dato_faltante": False,
                    }
        else:
            if racha_actual is not None:
                # La racha se cortó. Identificar por qué:
                if (d.fecha - racha_actual["fin"]).days > 1:
                    # Faltaron días físicos antes de este registro
                    racha_actual["interrumpida_por_dato_faltante"] = True
                elif d.tmax is None:
                    # El día existe pero el dato es nulo
                    racha_actual["interrumpida_por_dato_faltante"] = True
                else:
                    # La temperatura bajó normalmente
                    racha_actual["interrumpida_por_dato_faltante"] = False

                racha_actual["incidencia"] = racha_actual["duracion"] >= min_dias
                rachas.append(racha_actual)
                racha_actual = None

    if racha_actual is not None:
        racha_actual["incidencia"] = racha_actual["duracion"] >= min_dias
        rachas.append(racha_actual)

    return rachas
