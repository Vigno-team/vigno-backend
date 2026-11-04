"""Alta de estaciones nuevas desde la API."""

import re
import unicodedata

from django.conf import settings
from django.db import IntegrityError, transaction

from apps.clima.mapeos import buscar_estacion
from apps.clima.models import Estacion

MAX_CODIGO = 50
INTENTOS_CODIGO = 5


class NombreRepetido(Exception):
    def __init__(self, existente: Estacion):
        self.existente = existente
        super().__init__(f"Ya existe la estación {existente.nombre}")


def en_territorio(latitud: float, longitud: float, limites=None) -> bool:
    limites = limites or settings.INSTANCIA["limites_geograficos"]
    cajas = limites.get("estaciones", [[*limites["latitud"], *limites["longitud"]]])
    return any(
        lat_min <= latitud <= lat_max and lon_min <= longitud <= lon_max
        for lat_min, lat_max, lon_min, lon_max in cajas
    )


def base_de_codigo(nombre: str) -> str:
    """'Viña Los Álamos' -> 'vina-los-alamos'. Vacío si el nombre no tiene letras ni números."""
    ascii_ = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", ascii_.lower()).strip("-")[: MAX_CODIGO - 4].strip("-")


def codigo_libre(nombre: str) -> str:
    base = base_de_codigo(nombre)
    candidato, n = base, 1
    while Estacion.objects.filter(codigo=candidato).exists():
        n += 1
        candidato = f"{base}-{n}"
    return candidato


def crear_estacion(*, nombre, latitud, longitud, subzona=None, propietario=None) -> Estacion:
    """Crea la estación con un `codigo` único. Lanza NombreRepetido si el nombre ya existe."""
    for _ in range(INTENTOS_CODIGO):
        existente = buscar_estacion(nombre)
        if existente is not None:
            raise NombreRepetido(existente)
        try:
            with transaction.atomic():
                return Estacion.objects.create(
                    nombre=nombre,
                    codigo=codigo_libre(nombre),
                    latitud=latitud,
                    longitud=longitud,
                    subzona=subzona or None,
                    propietario=propietario or None,
                )
        except IntegrityError:
            # Otra petición creó el mismo nombre o el mismo código entre la consulta y el insert:
            # se vuelve a mirar y, si fue el código, se elige otro.
            continue
    raise RuntimeError("No se pudo asignar un código único a la estación")
