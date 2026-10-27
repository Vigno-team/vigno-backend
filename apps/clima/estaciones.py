"""Alta de estaciones nuevas desde la API."""

import re
import unicodedata

from django.db import IntegrityError, transaction

from apps.clima.mapeos import buscar_estacion
from apps.clima.models import Estacion

# Cajas (lat_min, lat_max, lon_min, lon_max) que cubren el territorio chileno donde puede haber
# viñas: el continente y las islas Juan Fernández y Rapa Nui. Es una revisión gruesa para
# atrapar errores de digitación (signo, coordenadas cruzadas), no un límite político: cerca de
# la frontera acepta puntos que ya son de Argentina, Bolivia o Perú. No incluye la Antártica.
CAJAS_CHILE = (
    (-56.6, -17.5, -75.7, -66.4),
    (-34.0, -33.5, -80.9, -78.5),
    (-27.3, -26.9, -109.6, -109.2),
)
MAX_CODIGO = 50
INTENTOS_CODIGO = 5


class NombreRepetido(Exception):
    def __init__(self, existente: Estacion):
        self.existente = existente
        super().__init__(f"Ya existe la estación {existente.nombre}")


def en_chile(latitud: float, longitud: float) -> bool:
    return any(
        lat_min <= latitud <= lat_max and lon_min <= longitud <= lon_max
        for lat_min, lat_max, lon_min, lon_max in CAJAS_CHILE
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
