"""Catálogo compartido de E1C-71; reutilizable en correcciones de E1C-131."""

import json
import math

from django.conf import settings

MOTIVO_RANGO = "Valor fuera de rango físico"
VARIABLES = {
    "temperatura_maxima": "tmax",
    "temperatura_minima": "tmin",
    "temperatura_media": "tmedia",
    "precipitacion": "precipitacion",
}


def cargar_rangos():
    with (settings.BASE_DIR / "config/rangos_variables.json").open(encoding="utf-8") as archivo:
        catalogo = json.load(archivo)
    for regla in [catalogo[k] for k in ("tmax", "tmin", "tmedia")] + [
        catalogo["precipitacion"][f] for f in ("D", "H")
    ]:
        if not all(math.isfinite(regla[k]) for k in ("min", "max")) or regla["min"] > regla["max"]:
            raise ValueError("Catálogo de rangos físicos inválido")
    return catalogo


def motivo_fuera_de_rango(variable, valor, frecuencia="D", catalogo=None):
    """None si es válido/nulo/no catalogado; motivo si no cumple. Límites inclusivos."""
    if frecuencia not in ("D", "H"):
        raise ValueError("Frecuencia debe ser D o H")
    clave = VARIABLES.get(variable, variable)
    if valor is None or clave not in VARIABLES.values():
        return None
    catalogo = cargar_rangos() if catalogo is None else catalogo
    regla = catalogo[clave]
    if clave == "precipitacion":
        regla = regla[frecuencia]
    if not math.isfinite(valor) or not regla["min"] <= valor <= regla["max"]:
        return f"{MOTIVO_RANGO}: {clave}={valor}; permitido [{regla['min']}, {regla['max']}] {regla['unidad']}"
    return None
