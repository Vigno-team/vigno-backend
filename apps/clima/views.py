"""API de solo lectura y health check del entorno."""

from django.db import connection
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.clima import estaciones, resultados, serializers, services
from apps.clima.models import Estacion
from apps.ingesta.autenticacion import ApiKeyAuthentication


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
    # GET sigue público (D4.1); solo POST pide la X-Api-Key de E1C-66.
    authentication_classes = [ApiKeyAuthentication]
    http_method_names = ["get", "post", "head", "options"]

    def get_permissions(self):
        # spectacular genera el esquema con una petición simulada que puede no traer método
        escribe = getattr(getattr(self, "request", None), "method", None) == "POST"
        return [IsAuthenticated()] if escribe else [AllowAny()]

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

    @extend_schema(
        summary="Da de alta una estación nueva",
        description=(
            "Requiere la cabecera X-Api-Key. El nombre es único sin distinguir mayúsculas ni "
            "tildes; si ya existe responde 409 con la estación existente. La estación queda con "
            "un `id` (código) propio, que se usa en `estacion=` de las demás consultas. Una "
            "estación sin mapeo propio carga sus Excel con el formato estándar."
        ),
        request=serializers.EstacionNuevaSerializer,
        responses={
            201: serializers.EstacionCreadaSerializer,
            400: None,
            401: serializers.ErrorDetalleSerializer,
            409: serializers.EstacionRepetidaSerializer,
        },
        operation_id="estaciones_crear",
        tags=["Estaciones"],
    )
    def post(self, request):
        entrada = serializers.EstacionNuevaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        try:
            estacion = estaciones.crear_estacion(**entrada.validated_data)
        except estaciones.NombreRepetido as repetida:
            return Response(
                {
                    "detail": f"Ya existe la estación {repetida.existente.nombre}.",
                    "estacion": serializers.EstacionCreadaSerializer(repetida.existente).data,
                },
                status=status.HTTP_409_CONFLICT,
            )
        return Response(
            serializers.EstacionCreadaSerializer(estacion).data, status=status.HTTP_201_CREATED
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


class HealthCheckView(APIView):
    """Verifica que la API responde y que la base de datos esta accesible."""

    authentication_classes = []
    permission_classes = []

    @extend_schema(
        summary="Estado del servicio",
        description=(
            "Devuelve el estado de la API y de la conexion a PostgreSQL. "
            "Lo usa el equipo para confirmar que el entorno levanto bien."
        ),
        responses={200: None, 503: None},
    )
    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            db_ok = True
        except Exception:
            db_ok = False

        payload = {
            "status": "ok" if db_ok else "degraded",
            "servicio": "vigno-backend",
            "version": "0.1.0",
            "base_datos": "conectada" if db_ok else "sin conexion",
        }
        codigo = status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(payload, status=codigo)
