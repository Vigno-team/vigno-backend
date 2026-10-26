"""Correcciones explícitas y reversibles. No completa valores por inferencia."""

import io
import logging
import math
from pathlib import Path

from django.core.management import call_command
from django.db import transaction
from django.db.models import Max, Min
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from apps.clima.management.commands.actualizar_todo import candado
from apps.clima.models import (
    CorreccionManual,
    Estacion,
    IndiceClimatico,
    MedicionHoraria,
    ResumenDiario,
)
from apps.clima.temporadas import temporada_de

logger = logging.getLogger(__name__)
CAMPOS_DATO = (
    "valor",
    "motivo_nulo",
    "fuera_de_rango",
    "motivo_fuera_de_rango",
    "origen",
    "temporada",
    "carga_id",
)


class ConflictoCorreccion(APIException):
    status_code = 409
    default_detail = "La corrección ya no está vigente. Consulta de nuevo la bitácora."


def valor_json(valor):
    return str(valor) if isinstance(valor, float) and not math.isfinite(valor) else valor


def _validar_periodo(estacion, timestamp, frecuencia):
    # Las correcciones no pueden extender por sí solas el histórico de una estación.
    periodo = MedicionHoraria.objects.filter(
        estacion=estacion,
        origen="excel",
        valor__isnull=False,
    ).aggregate(inicio=Min("timestamp"), fin=Max("timestamp"))
    fecha = timezone.localdate(timestamp)
    if fecha > timezone.localdate() or (frecuencia == "H" and timestamp > timezone.now()):
        raise ValidationError({"fecha": "No se pueden corregir datos futuros."})
    if periodo["inicio"] is None or not (
        timezone.localdate(periodo["inicio"]) <= fecha <= timezone.localdate(periodo["fin"])
    ):
        # Un dato de borde ya corregido conserva su fecha original como evidencia del período.
        originales = CorreccionManual.objects.filter(estacion=estacion, anterior__isnull=True)
        fechas = [
            timezone.localdate(c.timestamp)
            for c in originales
            if c.dato_anterior.get("existe")
            and c.dato_anterior.get("origen") == "excel"
            and c.valor_anterior is not None
        ]
        fechas += [timezone.localdate(v) for v in periodo.values() if v is not None]
        if not fechas or not min(fechas) <= fecha <= max(fechas):
            raise ValidationError(
                {"fecha": "La fecha debe estar dentro del período observado de la estación."}
            )
    frecuencias = set(
        MedicionHoraria.objects.filter(estacion=estacion, timestamp__date=fecha).values_list(
            "frecuencia", flat=True
        )
    )
    if (frecuencia == "D" and "H" in frecuencias) or (frecuencia == "H" and frecuencias == {"D"}):
        raise ValidationError(
            {
                "frecuencia": "Usa la frecuencia de los datos de ese día; no se mezclan correcciones diarias y horarias."
            }
        )


def _snapshot(dato):
    if dato is None:
        return {"existe": False}
    return {"existe": True, **{campo: valor_json(getattr(dato, campo)) for campo in CAMPOS_DATO}}


def _falla_original(estacion, timestamp, variable, frecuencia, dato, carga, fila):
    from apps.clima.fallas_rangos import _fila

    comunes = dict(
        fecha=timezone.localdate(timestamp).isoformat(),
        timestamp=timezone.localtime(timestamp).isoformat(),
        variable=variable,
        frecuencia=frecuencia,
    )
    if carga:
        rechazo = next(r for r in carga.detalle_rechazos if r.get("fila") == fila)
        return _fila(
            estacion,
            "rechazado",
            **comunes,
            carga=carga.pk,
            fila=fila,
            archivo=Path(carga.archivo.replace("\\", "/")).name,
            valor_original=rechazo.get("valor_original"),
            motivo=rechazo.get("motivo"),
        )
    if dato is not None:
        if dato.valor is not None and not dato.fuera_de_rango:
            return None
        return _fila(
            estacion,
            "fuera_de_rango" if dato.fuera_de_rango else "nulo",
            **comunes,
            medicion_id=dato.pk,
            valor_original=valor_json(dato.valor),
            motivo=dato.motivo_fuera_de_rango
            if dato.fuera_de_rango
            else dato.motivo_nulo or "Sin valor en origen",
            carga=dato.carga_id,
            archivo=Path(dato.carga.archivo.replace("\\", "/")).name if dato.carga else None,
        )
    hueco_corregido = CorreccionManual.objects.filter(
        estacion=estacion,
        timestamp__date=timezone.localdate(timestamp),
        estado=CorreccionManual.VIGENTE,
        falla_original__tipo="sin_registro",
    ).first()
    if hueco_corregido:
        return hueco_corregido.falla_original
    if not MedicionHoraria.objects.filter(
        estacion=estacion, timestamp__date=timezone.localdate(timestamp)
    ).exists():
        return _fila(
            estacion,
            "sin_registro",
            fecha=comunes["fecha"],
            motivo="Día sin mediciones dentro del período observado de la estación",
        )
    return None


def _invalidar_derivados(correccion):
    fecha = timezone.localdate(correccion.timestamp)
    # Al revertir el único dato de un día debe desaparecer también su resumen.
    ResumenDiario.objects.filter(estacion=correccion.estacion, fecha=fecha).delete()
    IndiceClimatico.objects.filter(
        estacion=correccion.estacion, temporada=temporada_de(fecha)
    ).delete()


def _reintegrar():
    try:
        call_command(
            "actualizar_todo", "--sin-satelite", stdout=io.StringIO(), stderr=io.StringIO()
        )
    except Exception:
        logger.exception("La corrección quedó guardada, pero falló su recálculo")
        return {
            "ok": False,
            "detalle": "El cambio quedó guardado. Reintenta el recálculo con: python manage.py actualizar_todo --sin-satelite. No repitas el POST.",
        }
    return {"ok": True}


def crear_correccion(datos):
    estacion = datos["estacion"]
    clave = {k: datos[k] for k in ("estacion", "timestamp", "variable", "frecuencia")}
    # El mismo candado de E1C-129 evita publicar una actualización anterior después de esta.
    with candado():
        with transaction.atomic():
            Estacion.objects.select_for_update().get(pk=estacion.pk)
            _validar_periodo(estacion, datos["timestamp"], datos["frecuencia"])
            dato = MedicionHoraria.objects.filter(**clave).select_related("carga").first()
            anterior = CorreccionManual.objects.filter(
                **clave, estado=CorreccionManual.VIGENTE
            ).first()
            carga = datos.get("carga_origen")
            fila = datos.get("fila_origen")
            if (
                anterior
                and carga
                and (carga.pk, fila) != (anterior.carga_origen_id, anterior.fila_origen)
            ):
                raise ValidationError(
                    {
                        "carga_origen": "Una corrección reemplazada conserva su carga y fila de origen."
                    }
                )
            falla = (
                anterior.falla_original
                if anterior
                else _falla_original(
                    estacion,
                    datos["timestamp"],
                    datos["variable"],
                    datos["frecuencia"],
                    dato,
                    carga,
                    fila,
                )
            )
            if anterior:
                _comprobar_actual(anterior, dato)
                anterior.estado = CorreccionManual.REEMPLAZADA
                anterior.save(update_fields=["estado"])
            correccion = CorreccionManual.objects.create(
                **clave,
                valor_anterior=dato.valor if dato else None,
                valor_nuevo=datos["valor_nuevo"],
                autor=datos["autor"],
                motivo=datos["motivo"],
                carga_origen=carga
                or (anterior.carga_origen if anterior else None)
                or (dato.carga if dato else None),
                fila_origen=fila or (anterior.fila_origen if anterior else None),
                anterior=anterior,
                dato_anterior=_snapshot(dato),
                falla_original=falla,
            )
            MedicionHoraria.objects.update_or_create(
                **clave,
                defaults={
                    "valor": datos["valor_nuevo"],
                    "origen": "manual",
                    "motivo_nulo": None,
                    "fuera_de_rango": False,
                    "motivo_fuera_de_rango": None,
                    "temporada": dato.temporada if dato else None,
                    "carga": dato.carga if dato else carga,
                },
            )
            _invalidar_derivados(correccion)
        actualizacion = _reintegrar()
    return correccion, actualizacion


def _comprobar_actual(correccion, dato):
    if (
        dato is None
        or dato.origen != "manual"
        or dato.valor != correccion.valor_nuevo
        or dato.fuera_de_rango
    ):
        raise ConflictoCorreccion(
            "La medición cambió después de la corrección; revisa su origen antes de continuar."
        )


def revertir_correccion(correccion_id, datos):
    from django.shortcuts import get_object_or_404

    with candado():
        with transaction.atomic():
            correccion = get_object_or_404(
                CorreccionManual.objects.select_for_update(), pk=correccion_id
            )
            if correccion.estado != CorreccionManual.VIGENTE:
                raise ConflictoCorreccion()
            Estacion.objects.select_for_update().get(pk=correccion.estacion_id)
            clave = {
                k: getattr(correccion, k)
                for k in ("estacion", "timestamp", "variable", "frecuencia")
            }
            dato = MedicionHoraria.objects.filter(**clave).first()
            _comprobar_actual(correccion, dato)
            previo = correccion.dato_anterior
            if previo["existe"]:
                for campo in CAMPOS_DATO:
                    valor = previo[campo]
                    setattr(
                        dato,
                        campo,
                        float(valor) if campo == "valor" and valor is not None else valor,
                    )
                dato.save()
            else:
                dato.delete()
            correccion.estado = CorreccionManual.REVERTIDA
            correccion.revertida_en = timezone.now()
            correccion.revertida_por = datos["autor"]
            correccion.motivo_reversion = datos["motivo"]
            correccion.save(
                update_fields=["estado", "revertida_en", "revertida_por", "motivo_reversion"]
            )
            if correccion.anterior_id:
                CorreccionManual.objects.filter(pk=correccion.anterior_id).update(
                    estado=CorreccionManual.VIGENTE
                )
            _invalidar_derivados(correccion)
        actualizacion = _reintegrar()
    return correccion, actualizacion
