"""API de solo lectura para E1C-46 y E1C-47."""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.clima import resultados, serializers, services
from apps.clima.models import Estacion


class ResultadosView(APIView):
    # La demo es pública y de solo lectura según el contrato D4.1.
    authentication_classes = []
    permission_classes = [AllowAny]
    http_method_names = ["get", "head", "options"]

    def consultar(self, request, temporada):
        consulta = serializers.ConsultaTemporadaSerializer(
            data={"estacion": request.query_params.get("estacion"), "temporada": temporada}
        )
        consulta.is_valid(raise_exception=True)
        datos = consulta.validated_data
        estacion = get_object_or_404(Estacion, codigo=datos["estacion"])
        return estacion, datos["temporada"]


PARAMETROS_TEMPORADA = [
    OpenApiParameter(
        "estacion", str, required=True, description="Código devuelto por /estaciones."
    ),
    OpenApiParameter(
        "temporada", str, location=OpenApiParameter.PATH, description="Dos años: 2024-2025."
    ),
]
ERRORES = {400: serializers.ErrorConsultaSerializer, 404: serializers.ErrorDetalleSerializer}


class EstacionesView(ResultadosView):
    @extend_schema(
        summary="Estaciones disponibles y calidad de sus datos",
        operation_id="resultados_estaciones_listar",
        responses=serializers.EstacionResultadoSerializer(many=True),
        tags=["Resultados"],
    )
    def get(self, request):
        return Response(
            serializers.EstacionResultadoSerializer(services.estaciones(), many=True).data
        )


class TemporadasView(ResultadosView):
    @extend_schema(
        summary="Temporadas disponibles, ordenadas de la más antigua a la más reciente",
        operation_id="resultados_temporadas_listar",
        responses={200: {"type": "array", "items": {"type": "string"}}},
        tags=["Resultados"],
    )
    def get(self, request):
        return Response(services.temporadas())


class FichaTemporadaView(ResultadosView):
    @extend_schema(
        summary="Resultados reales de una estación y temporada",
        operation_id="resultados_temporada_obtener",
        description=(
            "Lee índices ya calculados y reúne lluvia, calor y días críticos. "
            "No ejecuta la ingesta ni recalcula Winkler/Huglin. "
            "La clasificación de temporada permanece null hasta integrar E1C-18."
        ),
        parameters=PARAMETROS_TEMPORADA,
        responses={200: serializers.FichaTemporadaSerializer, **ERRORES},
        tags=["Resultados"],
    )
    def get(self, request, temporada):
        estacion, temporada = self.consultar(request, temporada)
        datos = resultados.ficha_temporada(estacion, temporada)
        return Response(serializers.FichaTemporadaSerializer(datos).data)


class RachasView(ResultadosView):
    @extend_schema(
        summary="Rachas de calor de una estación y temporada",
        operation_id="resultados_rachas_obtener",
        parameters=PARAMETROS_TEMPORADA,
        responses={200: serializers.RachasTemporadaSerializer, **ERRORES},
        tags=["Resultados"],
    )
    def get(self, request, temporada):
        estacion, temporada = self.consultar(request, temporada)
        datos = resultados.resultados_rachas(estacion, temporada)
        return Response(serializers.RachasTemporadaSerializer(datos).data)
