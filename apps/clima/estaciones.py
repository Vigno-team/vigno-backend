"""Alta y administración de estaciones desde la API."""

import io
import logging
import re
import unicodedata

from django.conf import settings
from django.core.management import call_command
from django.db import IntegrityError, transaction

from apps.clima.mapeos import buscar_estacion
from apps.clima.models import Estacion, IndiceClimatico, MedicionHoraria

logger = logging.getLogger(__name__)

MAX_CODIGO = 50
INTENTOS_CODIGO = 5


class NombreRepetido(Exception):
    def __init__(self, existente: Estacion):
        self.existente = existente
        super().__init__(f"Ya existe la estación {existente.nombre}")


class CodigoRepetido(Exception):
    def __init__(self, existente: Estacion):
        self.existente = existente
        super().__init__(f"El código {existente.codigo} ya es de {existente.nombre}")


class EstacionConHistorico(Exception):
    """El código de una estación con mediciones no se cambia."""


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


def crear_estacion(
    *,
    nombre,
    latitud,
    longitud,
    subzona=None,
    propietario=None,
    tipo=Estacion.Tipo.PROPIA,
) -> Estacion:
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
                    tipo=tipo,
                )
        except IntegrityError:
            # Otra petición creó el mismo nombre o el mismo código entre la consulta y el insert:
            # se vuelve a mirar y, si fue el código, se elige otro.
            continue
    raise RuntimeError("No se pudo asignar un código único a la estación")


def _revisar_repetidos(estacion: Estacion, cambios: dict) -> None:
    if "nombre" in cambios:
        existente = buscar_estacion(cambios["nombre"])
        if existente is not None and existente.pk != estacion.pk:
            raise NombreRepetido(existente)

    if "codigo" in cambios:
        existente = (
            Estacion.objects.filter(codigo=cambios["codigo"]).exclude(pk=estacion.pk).first()
        )
        if existente is not None:
            raise CodigoRepetido(existente)


def editar_estacion(estacion: Estacion, **cambios) -> Estacion:
    """Aplica un PATCH y guarda únicamente los campos recibidos."""

    if (
        "codigo" in cambios
        and cambios["codigo"] != estacion.codigo
        and MedicionHoraria.objects.filter(estacion=estacion).exists()
    ):
        raise EstacionConHistorico()

    _revisar_repetidos(estacion, cambios)

    for campo in ("subzona", "propietario"):
        if campo in cambios:
            cambios[campo] = cambios[campo] or None

    for campo, valor in cambios.items():
        setattr(estacion, campo, valor)

    try:
        with transaction.atomic():
            estacion.save(update_fields=list(cambios))

            if estacion.tipo == Estacion.Tipo.REFERENCIA:
                IndiceClimatico.objects.filter(estacion=estacion).delete()
    except IntegrityError:
        _revisar_repetidos(estacion, cambios)
        raise

    return estacion


def cambiar_activa(estacion: Estacion, activa: bool) -> bool:
    """Activa o desactiva sin borrar datos."""

    if estacion.activa == activa:
        return False

    estacion.activa = activa
    estacion.save(update_fields=["activa"])
    return True


def recalcular() -> dict:
    """Regenera los datos del frontend después de un cambio."""

    try:
        call_command(
            "actualizar_todo",
            "--sin-satelite",
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        )
    except Exception:
        logger.exception("La estación cambió, pero falló el recálculo")
        return {
            "ok": False,
            "detalle": (
                "El cambio quedó guardado. Reintenta el recálculo con: "
                "python manage.py actualizar_todo --sin-satelite. "
                "No repitas la petición."
            ),
        }

    return {"ok": True}
