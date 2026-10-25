"""Mapeo de columnas de cada estación (config/mapeos_estaciones.json).

Una estación usa su mapeo propio si lo tiene; si no, la plantilla `formato_estandar`.
Lo comparten `ingestar_excel` y la carga por API
"""

import json
import re
import unicodedata

PLANTILLA = "formato_estandar"


class EstacionNoExiste(LookupError):
    """El nombre no corresponde a ninguna estación registrada."""

    def __init__(self, nombre: str):
        self.nombre = nombre
        super().__init__(f"La estación {nombre} no existe; créala primero")


def normalizar_nombre(nombre: str) -> str:
    """Clave para comparar nombres sin distinguir mayúsculas, tildes ni espacios sobrantes."""
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFKD", nombre) if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", sin_tildes).strip().casefold()


def es_nombre_reservado(nombre: str) -> bool:
    """`formato_estandar` es la plantilla del JSON: ninguna estación puede llamarse así."""
    return normalizar_nombre(nombre).replace("_", " ") == PLANTILLA.replace("_", " ")


def cargar_mapeos(ruta=None) -> dict:
    if ruta is None:
        from django.conf import settings

        ruta = settings.BASE_DIR / "config" / "mapeos_estaciones.json"
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def mapeo_de(nombre_estacion: str, mapeos: dict | None = None) -> dict:
    """Mapeo propio de la estación o, si no tiene, la plantilla `formato_estandar`."""
    if mapeos is None:
        mapeos = cargar_mapeos()
    clave = normalizar_nombre(nombre_estacion)
    for nombre, mapeo in mapeos.items():
        if nombre != PLANTILLA and normalizar_nombre(nombre) == clave:
            return mapeo
    if PLANTILLA not in mapeos:
        raise KeyError(f"Falta la plantilla '{PLANTILLA}' en mapeos_estaciones.json")
    return mapeos[PLANTILLA]


def buscar_estacion(nombre: str):
    """La estación registrada con ese nombre (sin distinguir mayúsculas ni tildes) o None."""
    from apps.clima.models import Estacion

    clave = normalizar_nombre(nombre)
    for estacion in Estacion.objects.order_by("id"):
        if normalizar_nombre(estacion.nombre) == clave:
            return estacion
    return None


def estacion_y_mapeo(nombre: str):
    """Estación registrada y su mapeo. Lanza EstacionNoExiste si no está en la base."""
    estacion = buscar_estacion(nombre)
    if estacion is None:
        raise EstacionNoExiste(nombre)
    return estacion, mapeo_de(estacion.nombre)
