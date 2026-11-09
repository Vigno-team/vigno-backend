"""API de solo lectura y health check del entorno."""

from django.conf import settings
from django.db import connection, transaction
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.registro import Accion, instantanea_estacion, registrar
from apps.clima import estaciones, resultados, serializers, services
from apps.clima.models import Estacion
from apps.cuentas.permisos import (
    EsAdministrador,
    LeerOEditar,
    PuedeEditar,
    PuedeLeer,
)


class ResultadosView(APIView):
    # Lecturas del dashboard: cualquier rol, o sin token mientras API_LECTURA_PUBLICA esté
    permission_classes = [PuedeLeer]
    lectura_publica = True
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


class EstacionesView(LeerOEditar, ResultadosView):
    # El GET es una lectura del dashboard; el POST (E1C-68) pide rol editor o administrador.
    http_method_names = ["get", "post", "head", "options"]

    @extend_schema(
        summary="Estaciones disponibles y calidad de sus datos",
        operation_id="resultados_estaciones_listar",
        responses=serializers.EstacionResultadoSerializer(many=True),
        tags=["Resultados"],
    )
    def get(self, request):
        incluir_inactivas = request.query_params.get(
            "incluir_inactivas"
        ) == "1" and EsAdministrador().has_permission(request, self)

        datos = services.estaciones(incluir_inactivas=incluir_inactivas)

        return Response(serializers.EstacionResultadoSerializer(datos, many=True).data)

    @extend_schema(
        summary="Da de alta una estación nueva",
        description=(
            "Requiere rol editor o administrador. El nombre es único sin distinguir mayúsculas "
            "ni tildes; si ya existe responde 409 con la estación existente. La estación queda "
            "con un `id` (código) propio, que se usa en `estacion=` de las demás consultas. Una "
            "estación sin mapeo propio carga sus Excel con el formato estándar."
        ),
        request=serializers.EstacionNuevaSerializer,
        responses={
            201: serializers.EstacionCreadaSerializer,
            400: None,
            401: serializers.ErrorDetalleSerializer,
            403: serializers.ErrorDetalleSerializer,
            409: serializers.EstacionRepetidaSerializer,
        },
        operation_id="estaciones_crear",
        tags=["Estaciones"],
    )
    def post(self, request):
        entrada = serializers.EstacionNuevaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)

        try:
            # El alta y su registro en la bitácora se guardan juntos o ninguno.
            with transaction.atomic():
                estacion = estaciones.crear_estacion(**entrada.validated_data)

                registrar(
                    Accion.ESTACION_ALTA,
                    request=request,
                    objeto=estacion,
                    nuevo=instantanea_estacion(estacion),
                )

        except estaciones.NombreRepetido as repetida:
            return Response(
                {
                    "detail": f"Ya existe la estación {repetida.existente.nombre}.",
                    "estacion": serializers.EstacionCreadaSerializer(repetida.existente).data,
                },
                status=status.HTTP_409_CONFLICT,
            )

        respuesta = serializers.EstacionCreadaSerializer(estacion).data

        return Response(
            respuesta,
            status=status.HTTP_201_CREATED,
        )


class EstacionDetalleView(APIView):
    lectura_publica = True
    http_method_names = ["get", "patch", "delete", "head", "options"]

    def get_permissions(self):
        if self.request.method == "DELETE":
            return [EsAdministrador()]

        if self.request.method == "PATCH":
            return [PuedeEditar()]

        return [PuedeLeer()]

    def obtener_estacion(self, codigo):
        consulta = Estacion.objects.all()

        # Los usuarios sin rol administrador solo pueden acceder
        # a estaciones activas.
        if not EsAdministrador().has_permission(self.request, self):
            consulta = consulta.filter(activa=True)

        return get_object_or_404(consulta, codigo=codigo)

    @extend_schema(
        summary="Consultar una estación",
        responses=serializers.EstacionDetalleSerializer,
        tags=["Estaciones"],
    )
    def get(self, request, codigo):
        estacion = self.obtener_estacion(codigo)

        return Response(serializers.EstacionDetalleSerializer(estacion).data)

    @extend_schema(
        summary="Editar una estación",
        request=serializers.EstacionEdicionSerializer,
        responses={
            200: serializers.EstacionDetalleSerializer,
            400: None,
            404: serializers.ErrorDetalleSerializer,
            409: serializers.EstacionRepetidaSerializer,
        },
        tags=["Estaciones"],
    )
    def patch(self, request, codigo):
        estacion = self.obtener_estacion(codigo)

        entrada = serializers.EstacionEdicionSerializer(
            estacion,
            data=request.data,
            partial=True,
        )
        entrada.is_valid(raise_exception=True)

        if not entrada.validated_data:
            return Response(
                {"detail": "Debes enviar al menos un campo para actualizar."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        anterior = instantanea_estacion(estacion)

        try:
            with transaction.atomic():
                estaciones.editar_estacion(
                    estacion,
                    **entrada.validated_data,
                )

                nuevo = instantanea_estacion(estacion)
                cambio = anterior != nuevo

                if cambio:
                    registrar(
                        Accion.ESTACION_EDICION,
                        request=request,
                        objeto=estacion,
                        anterior=anterior,
                        nuevo=nuevo,
                    )

        except estaciones.NombreRepetido as repetida:
            return Response(
                {
                    "detail": f"Ya existe la estación {repetida.existente.nombre}.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        except estaciones.CodigoRepetido as repetida:
            return Response(
                {
                    "detail": f"El código {repetida.existente.codigo} ya está utilizado.",
                },
                status=status.HTTP_409_CONFLICT,
            )

        except estaciones.EstacionConHistorico:
            return Response(
                {
                    "detail": (
                        "No se puede cambiar el código de una estación " "que ya tiene mediciones."
                    )
                },
                status=status.HTTP_409_CONFLICT,
            )

        resultado_recalculo = None

        if cambio:
            resultado_recalculo = estaciones.recalcular()

        respuesta = serializers.EstacionDetalleSerializer(estacion).data

        if resultado_recalculo is not None:
            respuesta["recalculo"] = resultado_recalculo

        return Response(respuesta)

    @extend_schema(
        summary="Desactivar una estación",
        responses={
            200: serializers.EstacionDetalleSerializer,
            404: serializers.ErrorDetalleSerializer,
        },
        tags=["Estaciones"],
    )
    def delete(self, request, codigo):
        estacion = self.obtener_estacion(codigo)
        anterior = instantanea_estacion(estacion)

        with transaction.atomic():
            cambio = estaciones.cambiar_activa(estacion, False)

            if cambio:
                registrar(
                    Accion.ESTACION_BAJA,
                    request=request,
                    objeto=estacion,
                    anterior=anterior,
                    nuevo=instantanea_estacion(estacion),
                )
        resultado_recalculo = None

        if cambio:
            resultado_recalculo = estaciones.recalcular()

        respuesta = serializers.EstacionDetalleSerializer(estacion).data

        if resultado_recalculo is not None:
            respuesta["recalculo"] = resultado_recalculo

        return Response(respuesta)


class ReactivarEstacionView(GenericAPIView):
    serializer_class = serializers.EstacionDetalleSerializer
    permission_classes = [EsAdministrador]
    http_method_names = ["post", "options"]

    @extend_schema(
        summary="Reactivar una estación",
        responses={
            200: serializers.EstacionDetalleSerializer,
            404: serializers.ErrorDetalleSerializer,
        },
        tags=["Estaciones"],
    )
    def post(self, request, codigo):
        estacion = get_object_or_404(Estacion, codigo=codigo)
        anterior = instantanea_estacion(estacion)

        with transaction.atomic():
            cambio = estaciones.cambiar_activa(estacion, True)

            if cambio:
                registrar(
                    Accion.ESTACION_EDICION,
                    request=request,
                    objeto=estacion,
                    anterior=anterior,
                    nuevo=instantanea_estacion(estacion),
                )

        resultado_recalculo = None

        if cambio:
            resultado_recalculo = estaciones.recalcular()

        respuesta = serializers.EstacionDetalleSerializer(estacion).data

        if resultado_recalculo is not None:
            respuesta["recalculo"] = resultado_recalculo

        return Response(respuesta)


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
    permission_classes = [AllowAny]

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
            "servicio": settings.INSTANCIA["organizacion"]["nombre_corto"],
            "version": "0.1.0",
            "base_datos": "conectada" if db_ok else "sin conexion",
        }
        codigo = status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(payload, status=codigo)
