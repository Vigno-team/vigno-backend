"""Reporte de calidad sin modificar ni completar las mediciones de origen."""

import csv
import io
import math
import re
from collections import Counter
from datetime import timedelta
from pathlib import Path

import pandas as pd
from django.db.models import Max, Min
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.response import Response

from apps.clima.models import Estacion, MedicionHoraria
from apps.clima.serializers import ConsultaTemporadaSerializer
from apps.clima.temporadas import rango_temporada
from apps.clima.views import ResultadosView
from apps.ingesta.models import RegistroCarga


def fallas_fuera_de_rango(estacion, temporada):
    inicio, fin = rango_temporada(temporada)
    mediciones = (
        MedicionHoraria.objects.filter(
            estacion=estacion,
            fuera_de_rango=True,
            timestamp__date__gte=inicio,
            timestamp__date__lte=fin,
        )
        .select_related("carga")
        .order_by("timestamp", "variable", "frecuencia")
    )
    filas = []
    for dato in mediciones:
        valor = dato.valor
        if valor is not None and not math.isfinite(valor):
            valor = str(valor)
        filas.append(
            {
                "medicion_id": dato.pk,
                "estacion": estacion.codigo,
                "fecha": timezone.localtime(dato.timestamp).date().isoformat(),
                "timestamp": timezone.localtime(dato.timestamp).isoformat(),
                "variable": dato.variable,
                "frecuencia": dato.frecuencia,
                "tipo": "fuera_de_rango",
                "motivo": dato.motivo_fuera_de_rango,
                "valor_original": valor,
                "archivo": Path(dato.carga.archivo.replace("\\", "/")).name if dato.carga else None,
                "carga": dato.carga_id,
                "corregido": False,
            }
        )
    return filas


TIPOS = ("rechazado", "nulo", "sin_registro", "fuera_de_rango")


def _fila(estacion, tipo, **datos):
    return {
        "medicion_id": None,
        "estacion": estacion.codigo,
        "fecha": None,
        "timestamp": None,
        "variable": None,
        "frecuencia": None,
        "tipo": tipo,
        "motivo": None,
        "valor_original": None,
        "archivo": None,
        "carga": None,
        "fila": None,
        "corregido": False,
        **datos,
    }


def reporte_fallas(estacion, temporada):
    inicio, fin = rango_temporada(temporada)
    mediciones = MedicionHoraria.objects.filter(estacion=estacion)
    periodo = mediciones.aggregate(inicio=Min("timestamp"), fin=Max("timestamp"))
    dentro = mediciones.filter(timestamp__date__gte=inicio, timestamp__date__lte=fin)
    filas = fallas_fuera_de_rango(estacion, temporada)
    for fila in filas:
        fila["fila"] = None
    for dato in dentro.filter(valor__isnull=True, fuera_de_rango=False).select_related("carga"):
        filas.append(
            _fila(
                estacion,
                "nulo",
                medicion_id=dato.pk,
                fecha=timezone.localdate(dato.timestamp).isoformat(),
                timestamp=timezone.localtime(dato.timestamp).isoformat(),
                variable=dato.variable,
                frecuencia=dato.frecuencia,
                motivo=dato.motivo_nulo or "Sin valor en origen",
                archivo=Path(dato.carga.archivo.replace("\\", "/")).name if dato.carga else None,
                carga=dato.carga_id,
            )
        )
    if periodo["inicio"] is not None:
        primero = max(inicio, timezone.localdate(periodo["inicio"]))
        ultimo = min(fin, timezone.localdate(periodo["fin"]), timezone.localdate())
        presentes = set(dentro.dates("timestamp", "day"))
        dia = primero
        while dia <= ultimo:
            if dia not in presentes:
                filas.append(
                    _fila(
                        estacion,
                        "sin_registro",
                        fecha=dia.isoformat(),
                        motivo="Día sin mediciones dentro del período observado de la estación",
                    )
                )
            dia += timedelta(days=1)
    for carga in RegistroCarga.objects.filter(estacion=estacion.nombre).order_by("pk"):
        for rechazo in carga.detalle_rechazos or []:
            original = rechazo.get("valor_original")
            fecha = None
            if isinstance(original, str) and re.search(
                r"(?:\d{4}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}[-/]\d{1,2}[-/]\d{4})", original
            ):
                fecha = pd.to_datetime(
                    original, errors="coerce", dayfirst=not bool(re.match(r"\d{4}[-/]", original))
                )
                if not pd.isna(fecha) and fecha.tzinfo is not None:
                    fecha = fecha.tz_convert(timezone.get_current_timezone())
            fecha = None if fecha is None or pd.isna(fecha) else fecha.date()
            if fecha is not None:
                if not inicio <= fecha <= fin:
                    continue
                criterio = "fecha_original"
            else:
                # El año del archivo no identifica una temporada agrícola exacta.
                if carga.temporada not in (inicio.year, fin.year):
                    continue
                criterio = "anio_archivo_fecha_desconocida"
            filas.append(
                _fila(
                    estacion,
                    "rechazado",
                    fecha=fecha.isoformat() if fecha else None,
                    variable="timestamp",
                    motivo=rechazo.get("motivo"),
                    valor_original=original,
                    fila=rechazo.get("fila"),
                    archivo=Path(carga.archivo.replace("\\", "/")).name,
                    carga=carga.pk,
                    criterio_temporada=criterio,
                )
            )
    return sorted(
        filas, key=lambda f: (f["fecha"] or "", f["tipo"], f["variable"] or "", f["carga"] or 0)
    )


class FallasRangosView(ResultadosView):
    @extend_schema(
        summary="Reporte de fallas de datos por estación y temporada",
        parameters=[
            OpenApiParameter("estacion", str, required=True),
            OpenApiParameter("temporada", str, required=True),
            OpenApiParameter("formato", str, enum=["json", "csv"]),
        ],
        responses={200: {"type": "object"}},
        tags=["Calidad"],
    )
    def get(self, request):
        consulta = ConsultaTemporadaSerializer(data=request.query_params)
        consulta.is_valid(raise_exception=True)
        datos = consulta.validated_data
        if int(datos["temporada"][:4]) > 9998:
            raise serializers.ValidationError({"temporada": "Temporada fuera del rango de fechas"})
        formato = request.query_params.get("formato", "json")
        if formato not in ("json", "csv"):
            raise serializers.ValidationError({"formato": "Usa json o csv"})
        estacion = get_object_or_404(Estacion, codigo=datos["estacion"])
        filas = reporte_fallas(estacion, datos["temporada"])
        if formato == "csv":
            salida = io.StringIO()
            campos = [
                "estacion",
                "fecha",
                "variable",
                "frecuencia",
                "tipo",
                "motivo",
                "valor_original",
                "archivo",
                "carga",
                "fila",
                "corregido",
            ]
            escritor = csv.writer(salida, delimiter=";")
            escritor.writerow(
                [
                    "Estación",
                    "Fecha",
                    "Variable",
                    "Frecuencia",
                    "Tipo",
                    "Motivo",
                    "Valor original",
                    "Archivo",
                    "Carga",
                    "Fila",
                    "Corregido",
                ]
            )
            for fila in filas:
                valores = []
                for campo in campos:
                    valor = fila[campo]
                    if campo == "corregido":
                        valor = "Sí" if valor else "No"
                    if isinstance(valor, str) and valor.startswith(("=", "+", "-", "@")):
                        valor = "'" + valor
                    valores.append(valor)
                escritor.writerow(valores)
            respuesta = HttpResponse(salida.getvalue(), content_type="text/csv; charset=utf-8")
            respuesta["Content-Disposition"] = 'attachment; filename="fallas-calidad.csv"'
            return respuesta
        return Response(
            {
                "estacion": estacion.codigo,
                "temporada": datos["temporada"],
                "tipos_incluidos": list(TIPOS),
                "fallas": filas,
                "resumen": {
                    "total": len(filas),
                    "por_tipo": {tipo: sum(f["tipo"] == tipo for f in filas) for tipo in TIPOS},
                    "por_variable": dict(Counter(f["variable"] or "sin_variable" for f in filas)),
                },
            }
        )
