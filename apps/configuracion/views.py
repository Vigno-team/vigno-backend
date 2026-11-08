"""GET/PATCH /api/v1/configuracion y PUT /api/v1/configuracion/logo."""

from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import SAFE_METHODS, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.auditoria.registro import Accion, registrar
from apps.clima.datos_frontend import PARAMETROS_CACHE, _respuesta_condicional
from apps.configuracion.models import ConfiguracionInstancia
from apps.configuracion.serializers import (
    CAMPOS_EDITABLES,
    ConfiguracionSerializer,
    LogoSerializer,
)
from apps.cuentas.permisos import EsAdministrador


def instantanea(configuracion) -> dict:
    """Lo que queda en la bitácora: los campos editables y el archivo del logo."""
    return {
        **{campo: getattr(configuracion, campo) for campo in CAMPOS_EDITABLES},
        "logo": configuracion.logo.name or None,
    }


def _bloqueada():
    """La fila, bloqueada hasta el fin de la transacción: dos ediciones a la vez no se pisan."""
    ConfiguracionInstancia.actual()  # la crea si es la primera vez
    return ConfiguracionInstancia.objects.select_for_update().get(pk=ConfiguracionInstancia.UNICA)


class ConfiguracionView(APIView):
    def get_permissions(self):
        # Pública al leer: la pantalla de login la necesita antes de entrar.
        if self.request.method in SAFE_METHODS:
            return [AllowAny()]
        return [EsAdministrador()]

    def perform_authentication(self, request):
        # Al leer no se mira el token: uno vencido guardado en el navegador daría 401
        # aunque la ruta sea pública. Al editar, sí (EsAdministrador lo necesita).
        if request.method not in SAFE_METHODS:
            super().perform_authentication(request)

    @extend_schema(
        summary="Marca de la instancia",
        operation_id="configuracion_leer",
        tags=["Configuración"],
        description=(
            "Pública, sin token. Nombre de la organización y del sistema, logo (URL o null), "
            "colores #RRGGBB, tipografía y pie. Usa ETag y Cache-Control: no-cache, igual que "
            "/datos."
        ),
        parameters=PARAMETROS_CACHE,
        responses={
            200: ConfiguracionSerializer,
            304: OpenApiResponse(description="Sin cambios; sin cuerpo"),
        },
    )
    def get(self, request):
        datos = ConfiguracionSerializer(
            ConfiguracionInstancia.actual(), context={"request": request}
        ).data
        return _respuesta_condicional(request, datos)

    @extend_schema(
        summary="Cambia textos y colores de la marca",
        operation_id="configuracion_editar",
        tags=["Configuración"],
        description=(
            "Solo administrador. Envía solo los campos que cambian. Queda en la bitácora con el "
            "valor anterior y el nuevo."
        ),
        request=ConfiguracionSerializer,
        responses={200: ConfiguracionSerializer, 400: None, 401: None, 403: None},
    )
    def patch(self, request):
        # El cambio y su registro en la bitácora se guardan juntos o ninguno.
        with transaction.atomic():
            configuracion = _bloqueada()
            anterior = instantanea(configuracion)
            entrada = ConfiguracionSerializer(
                configuracion, data=request.data, partial=True, context={"request": request}
            )
            entrada.is_valid(raise_exception=True)
            entrada.save()
            nuevo = instantanea(configuracion)
            if nuevo != anterior:
                registrar(
                    Accion.MARCA_EDICION,
                    request=request,
                    objeto=configuracion,
                    anterior=anterior,
                    nuevo=nuevo,
                )
        return Response(entrada.data)


class LogoView(APIView):
    permission_classes = [EsAdministrador]
    parser_classes = [MultiPartParser]

    @extend_schema(
        summary="Reemplaza el logo",
        operation_id="configuracion_logo",
        tags=["Configuración"],
        description=(
            "Solo administrador. multipart/form-data con el campo logo: PNG, JPG o WebP de hasta "
            "1 MB y 4096 × 4096 px. Se valida el contenido, no la extensión; SVG no se acepta. "
            "Devuelve la configuración completa con la URL nueva."
        ),
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {"logo": {"type": "string", "format": "binary"}},
                "required": ["logo"],
            }
        },
        responses={200: ConfiguracionSerializer, 400: None, 401: None, 403: None},
    )
    def put(self, request):
        entrada = LogoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        with transaction.atomic():
            configuracion = _bloqueada()
            anterior = instantanea(configuracion)
            logo_viejo = configuracion.logo.name
            configuracion.logo = entrada.validated_data["logo"]
            configuracion.save()  # aquí se escribe el archivo nuevo en MEDIA_ROOT
            registrar(
                Accion.LOGO_EDICION,
                request=request,
                objeto=configuracion,
                anterior=anterior,
                nuevo=instantanea(configuracion),
            )
            if logo_viejo:
                almacen = configuracion.logo.storage
                # Se borra solo si la transacción se confirma: si falla, el viejo sigue sirviendo.
                transaction.on_commit(lambda: almacen.delete(logo_viejo))
        return Response(ConfiguracionSerializer(configuracion, context={"request": request}).data)
