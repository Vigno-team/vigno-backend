"""Bloque fuera_de_rango de E1C-71, ampliable por el reporte de E1C-70."""

import csv
import io
import math
from collections import Counter
from pathlib import Path

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


class FallasRangosView(ResultadosView):
    @extend_schema(
        summary="Valores fuera de rango físico (bloque E1C-71 del reporte de fallas)",
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
        filas = fallas_fuera_de_rango(estacion, datos["temporada"])
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
            respuesta["Content-Disposition"] = 'attachment; filename="fallas-fuera-de-rango.csv"'
            return respuesta
        return Response(
            {
                "estacion": estacion.codigo,
                "temporada": datos["temporada"],
                "tipos_incluidos": ["fuera_de_rango"],
                "fallas": filas,
                "resumen": {
                    "total": len(filas),
                    "por_tipo": {"fuera_de_rango": len(filas)},
                    "por_variable": dict(Counter(f["variable"] for f in filas)),
                },
            }
        )
