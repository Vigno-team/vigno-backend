"""Selección reversible de columnas, con procedencia y auditoría de la carga."""

import re
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from apps.auditoria.registro import Accion, registrar
from apps.clima.mapeos import EstacionNoExiste, estacion_y_mapeo
from apps.clima.models import MedicionHoraria
from apps.ingesta import carga
from apps.ingesta.models import RegistroCarga
from apps.ingesta.variables import VARIABLES


class ConflictoSeleccion(APIException):
    status_code = 409
    default_detail = "No se puede determinar la procedencia de la carga."


def _instantanea(registro):
    return {
        "variables_procesadas": list(registro.variables_procesadas),
        "variables_excluidas": list(registro.variables_excluidas),
    }


def _vincular_antiguas(registro, estacion):
    """El intervalo solo atribuye filas sin FK cuando hay una única carga posible."""
    if not registro.fecha_desde or not registro.fecha_hasta:
        return
    pendientes = MedicionHoraria.objects.filter(
        estacion=estacion,
        carga__isnull=True,
        origen="excel",
        timestamp__date__range=(registro.fecha_desde, registro.fecha_hasta),
    )
    candidatas = list(
        RegistroCarga.objects.filter(
            estacion=registro.estacion,
            estado=RegistroCarga.ESTADO_OK,
            fecha_desde__lte=registro.fecha_hasta,
            fecha_hasta__gte=registro.fecha_desde,
        )
    )
    ids = []
    for medicion in pendientes:
        fecha = timezone.localdate(medicion.timestamp)
        posibles = [
            c
            for c in candidatas
            if c.fecha_desde <= fecha <= c.fecha_hasta
            and (not c.variables_procesadas or medicion.variable in c.variables_procesadas)
        ]
        if len(posibles) != 1:
            raise ConflictoSeleccion(
                "Hay mediciones antiguas sin carga identificada y archivos con fechas solapadas. "
                "Identifica su procedencia antes de cambiar la selección."
            )
        if posibles[0].pk == registro.pk:
            ids.append(medicion.pk)
    MedicionHoraria.objects.filter(pk__in=ids).update(carga=registro)


def _preparar_original(registro, estacion, config):
    extension = Path(registro.archivo).suffix.lower()
    if not re.fullmatch(r"[a-f0-9]{64}", registro.hash_archivo or "") or extension not in (
        ".xls",
        ".xlsx",
    ):
        raise ConflictoSeleccion(
            "No está disponible el Excel original; vuelve a subirlo con las variables que necesitas."
        )
    ruta = settings.DATOS_DIR / "cargas" / f"{registro.hash_archivo}{extension}"
    try:
        hash_original = carga.hash_archivo(ruta.read_bytes())
    except OSError as exc:
        raise ConflictoSeleccion(
            "No está disponible el Excel original; vuelve a subirlo con las variables que necesitas."
        ) from exc
    if hash_original != registro.hash_archivo:
        raise ConflictoSeleccion(
            "No está disponible el Excel original; vuelve a subirlo con las variables que necesitas."
        )
    try:
        return carga.preparar(ruta, registro.archivo, estacion, config, registro.temporada)
    except carga.ErrorCarga as exc:
        raise ConflictoSeleccion(str(exc)) from exc


@transaction.atomic
def cambiar_seleccion(pk, datos, request=None):
    if not isinstance(datos, dict) or set(datos) != {"variables_excluidas"}:
        raise ValidationError(
            {"variables_excluidas": "Envía únicamente la lista variables_excluidas."}
        )
    excluidas = datos["variables_excluidas"]
    if not isinstance(excluidas, list) or any(
        not isinstance(v, str) or v not in VARIABLES for v in excluidas
    ):
        raise ValidationError(
            {"variables_excluidas": "Debe ser una lista de variables del catálogo."}
        )
    excluidas = sorted(set(excluidas))
    registro = get_object_or_404(RegistroCarga.objects.select_for_update(), pk=pk)
    if registro.estado != RegistroCarga.ESTADO_OK:
        raise ConflictoSeleccion("Solo se puede cambiar la selección de una carga exitosa.")
    nombres = list(
        registro.mediciones_generadas.values_list("estacion__nombre", flat=True).distinct()
    )
    try:
        estacion, config = estacion_y_mapeo(nombres[0] if len(nombres) == 1 else registro.estacion)
    except EstacionNoExiste as exc:
        raise ConflictoSeleccion(str(exc)) from exc
    formato = config["formatos"].get(registro.formato_detectado)
    disponibles = set(registro.variables_procesadas) | set(registro.variables_excluidas)
    if not disponibles:
        disponibles = (
            set(formato["columnas"]) - {"timestamp"}
            if formato
            else set(registro.mediciones_generadas.values_list("variable", flat=True))
        )
    if set(excluidas) - disponibles:
        raise ValidationError(
            {"variables_excluidas": "La lista contiene variables que no pertenecen a este Excel."}
        )
    anterior = _instantanea(registro)
    _vincular_antiguas(registro, estacion)
    if not registro.variables_procesadas:
        # Las cargas anteriores a E1C-136 procesaban todas las columnas del formato.
        registro.variables_procesadas = sorted(disponibles)
    adicionales = disponibles - set(excluidas) - set(registro.variables_procesadas)
    if adicionales:
        prep = _preparar_original(registro, estacion, config)
        errores = carga.validar_umbrales(
            prep, carga.cargar_umbrales(), variables=sorted(adicionales)
        )
        if errores:
            raise ValidationError({"variables_excluidas": errores})
        carga.incorporar_variables(prep, registro, sorted(adicionales))
    mediciones = registro.mediciones_generadas.filter(origen="excel")
    mediciones.filter(variable__in=excluidas).update(excluido=True)
    mediciones.exclude(variable__in=excluidas).update(excluido=False)
    registro.variables_excluidas = excluidas
    registro.save(update_fields=["variables_procesadas", "variables_excluidas"])
    registrar(
        Accion.CARGA_SELECCION,
        request=request,
        objeto=registro,
        anterior=anterior,
        nuevo=_instantanea(registro),
    )
    return registro
