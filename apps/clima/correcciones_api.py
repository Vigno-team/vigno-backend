"""Bitácora y endpoints de E1C-131. El autor es declarado hasta incorporar E1C-64."""

from datetime import datetime, time

import pandas as pd
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from pytz.exceptions import AmbiguousTimeError, NonExistentTimeError
from rest_framework import serializers
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.clima.correcciones import crear_correccion, revertir_correccion, valor_json
from apps.clima.models import CorreccionManual, Estacion
from apps.clima.rangos import VARIABLES, motivo_fuera_de_rango
from apps.ingesta.autenticacion import ApiKeyPrivadaAuthentication
from apps.ingesta.models import RegistroCarga


class AutorMotivoSerializer(serializers.Serializer):
    autor = serializers.CharField(max_length=100, allow_blank=False)
    motivo = serializers.CharField(max_length=1000, allow_blank=False)


class NuevaCorreccionSerializer(AutorMotivoSerializer):
    estacion = serializers.SlugRelatedField(slug_field="codigo", queryset=Estacion.objects.all())
    fecha = serializers.DateField()
    hora = serializers.TimeField(required=False, allow_null=True)
    variable = serializers.CharField()
    frecuencia = serializers.ChoiceField(choices=["D", "H"])
    valor_nuevo = serializers.FloatField()
    carga_origen = serializers.PrimaryKeyRelatedField(
        queryset=RegistroCarga.objects.all(), required=False, allow_null=True
    )
    fila_origen = serializers.IntegerField(min_value=1, required=False, allow_null=True)

    def validate_variable(self, valor):
        canonica = {v: k for k, v in VARIABLES.items()}.get(valor, valor)
        if canonica not in VARIABLES:
            raise serializers.ValidationError(
                "Usa tmax, tmin, tmedia, precipitacion o su nombre canónico."
            )
        return canonica

    def validate(self, datos):
        razon = motivo_fuera_de_rango(datos["variable"], datos["valor_nuevo"], datos["frecuencia"])
        if razon:
            raise serializers.ValidationError({"valor_nuevo": razon})
        hora = datos.pop("hora", None)
        fecha = datos.pop("fecha")
        if datos["frecuencia"] == "H" and hora is None:
            raise serializers.ValidationError(
                {"hora": "La hora es obligatoria para un dato horario."}
            )
        if datos["frecuencia"] == "D" and hora is not None:
            raise serializers.ValidationError({"hora": "Los datos diarios no llevan hora."})
        try:
            # Igual que E1C-117: no adivinar una hora repetida o inexistente por cambio de horario.
            datos["timestamp"] = (
                pd.Timestamp(datetime.combine(fecha, hora or time(12)))
                .tz_localize(
                    timezone.get_current_timezone_name(),
                    ambiguous="raise",
                    nonexistent="raise",
                )
                .to_pydatetime()
            )
        except (ValueError, TypeError, AmbiguousTimeError, NonExistentTimeError) as error:
            # pandas usa excepciones de pytz para ambos casos de horario de verano.
            raise serializers.ValidationError(
                {"hora": "Hora inexistente o ambigua en la zona horaria de la estación."}
            ) from error
        carga, fila = datos.get("carga_origen"), datos.get("fila_origen")
        if (carga is None) != (fila is None):
            raise serializers.ValidationError(
                {
                    "carga_origen": "Para una fila rechazada indica carga_origen y fila_origen juntas."
                }
            )
        if carga is not None:
            if carga.estacion != datos["estacion"].nombre:
                raise serializers.ValidationError(
                    {"carga_origen": "La carga no pertenece a esta estación."}
                )
            if not any(r.get("fila") == fila for r in carga.detalle_rechazos or []):
                raise serializers.ValidationError(
                    {"fila_origen": "Esta fila no figura entre los rechazos de la carga."}
                )
        return datos


class CorreccionSerializer(serializers.ModelSerializer):
    estacion = serializers.CharField(source="estacion.codigo")
    fecha = serializers.SerializerMethodField()
    hora = serializers.SerializerMethodField()
    valor_anterior = serializers.SerializerMethodField()

    def get_fecha(self, obj) -> str:
        return timezone.localdate(obj.timestamp).isoformat()

    def get_hora(self, obj) -> str | None:
        return (
            timezone.localtime(obj.timestamp).time().isoformat() if obj.frecuencia == "H" else None
        )

    def get_valor_anterior(self, obj) -> float | str | None:
        return valor_json(obj.valor_anterior)

    class Meta:
        model = CorreccionManual
        fields = [
            "id",
            "estacion",
            "fecha",
            "hora",
            "timestamp",
            "variable",
            "frecuencia",
            "valor_anterior",
            "valor_nuevo",
            "motivo",
            "autor",
            "creada_en",
            "estado",
            "carga_origen",
            "fila_origen",
            "reemplazada_por",
            "anterior",
            "revertida_en",
            "revertida_por",
            "motivo_reversion",
        ]
        read_only_fields = fields


class ResultadoCorreccionSerializer(serializers.Serializer):
    correccion = CorreccionSerializer()
    actualizacion = serializers.JSONField()


class CorreccionesView(GenericAPIView):
    authentication_classes = [ApiKeyPrivadaAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = CorreccionSerializer
    http_method_names = ["get", "post", "head", "options"]

    @extend_schema(
        summary="Bitácora de correcciones manuales",
        parameters=[OpenApiParameter("estacion", str, description="Código de la estación")],
        responses=CorreccionSerializer(many=True),
        tags=["Calidad"],
    )
    def get(self, request):
        correcciones = CorreccionManual.objects.select_related("estacion").all()
        if "estacion" in request.query_params:
            correcciones = correcciones.filter(estacion__codigo=request.query_params["estacion"])
        pagina = self.paginate_queryset(correcciones)
        return self.get_paginated_response(self.get_serializer(pagina, many=True).data)

    @extend_schema(
        summary="Corregir un dato y recalcular sin consultar el satélite",
        request=NuevaCorreccionSerializer,
        responses={201: ResultadoCorreccionSerializer, 503: ResultadoCorreccionSerializer},
        tags=["Calidad"],
    )
    def post(self, request):
        entrada = NuevaCorreccionSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        correccion, actualizacion = crear_correccion(entrada.validated_data)
        return Response(
            {"correccion": CorreccionSerializer(correccion).data, "actualizacion": actualizacion},
            status=201 if actualizacion["ok"] else 503,
        )


class RevertirCorreccionView(GenericAPIView):
    authentication_classes = [ApiKeyPrivadaAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = AutorMotivoSerializer
    http_method_names = ["post", "options"]

    @extend_schema(
        summary="Revertir una corrección vigente y recalcular",
        responses={200: ResultadoCorreccionSerializer, 503: ResultadoCorreccionSerializer},
        tags=["Calidad"],
    )
    def post(self, request, pk):
        entrada = self.get_serializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        correccion, actualizacion = revertir_correccion(pk, entrada.validated_data)
        return Response(
            {"correccion": CorreccionSerializer(correccion).data, "actualizacion": actualizacion},
            status=200 if actualizacion["ok"] else 503,
        )
