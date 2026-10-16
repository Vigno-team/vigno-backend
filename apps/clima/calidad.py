from collections.abc import Iterable
from datetime import date

from apps.clima.models import Estacion, ResumenDiario


def resolucion_desde_origenes(origenes: Iterable[str]) -> str | None:
    encontrados = set(origenes)
    if len(encontrados) > 1:
        return "mixta"
    return {"D": "diaria", "H": "horaria"}.get(next(iter(encontrados), None))


def resolucion_estacion(estacion: Estacion, inicio: date, fin: date) -> str | None:
    origenes = ResumenDiario.objects.filter(
        estacion=estacion, fecha__range=(inicio, fin)
    ).values_list("origen", flat=True)
    return resolucion_desde_origenes(origenes)


def construir_calidad_dato(completitud, confiable, umbral, resolucion, version):
    return {
        "completitud_pct": round(completitud, 1) if completitud is not None else None,
        "confiable": bool(confiable),
        "umbral_completitud_pct": umbral,
        "resolucion_origen": resolucion,
        "version_calculo": version,
    }
