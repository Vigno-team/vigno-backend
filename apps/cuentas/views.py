"""Rutas de /api/v1/auth (E1C-64). Solo el login y el refresco funcionan sin token."""

from django.db import transaction
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenViewBase

from apps.auditoria.registro import Accion, registrar
from apps.cuentas.models import Perfil, debe_cambiar_clave
from apps.cuentas.roles import ROLES
from apps.cuentas.serializers import (
    CambiarClaveSerializer,
    CerrarSesionSerializer,
    LoginSerializer,
    RefrescoSerializer,
    datos_usuario,
    invalidar_refrescos,
    tokens_para,
)

UsuarioSerializer = inline_serializer(
    "Usuario",
    {
        "id": serializers.IntegerField(),
        "nombre": serializers.CharField(),
        "email": serializers.EmailField(),
        "rol": serializers.ChoiceField(choices=list(ROLES), allow_null=True),
        "debe_cambiar_clave": serializers.BooleanField(),
    },
)
TokensSerializer = inline_serializer(
    "Tokens", {"access": serializers.CharField(), "refresh": serializers.CharField()}
)
ERROR = inline_serializer("ErrorAuth", {"detail": serializers.CharField()})


class LoginView(TokenViewBase):
    # TokenViewBase no autentica la petición (un token vencido en la cabecera no estorba)
    # y responde 401 con WWW-Authenticate cuando las credenciales no sirven.
    serializer_class = LoginSerializer
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    @extend_schema(
        summary="Entrar con correo y clave",
        description=(
            "Devuelve un token de acceso (15 min) y uno de refresco (8 h). Máximo 5 intentos "
            "por minuto por IP. La respuesta es la misma si el correo no existe o la clave "
            "es incorrecta."
        ),
        responses={
            200: inline_serializer(
                "LoginRespuesta",
                {
                    "access": serializers.CharField(),
                    "refresh": serializers.CharField(),
                    "usuario": UsuarioSerializer,
                },
            ),
            401: ERROR,
            429: ERROR,
        },
        auth=[],
        tags=["Cuentas"],
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class RefrescoView(TokenViewBase):
    serializer_class = RefrescoSerializer

    @extend_schema(
        summary="Cambiar el refresco por tokens nuevos",
        description="El refresco rota: el que se usó queda invalidado.",
        responses={200: TokensSerializer, 401: ERROR},
        auth=[],
        tags=["Cuentas"],
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class CerrarSesionView(APIView):
    permite_cambio_de_clave_pendiente = True

    @extend_schema(
        summary="Cerrar sesión: el refresco deja de servir",
        request=CerrarSesionSerializer,
        responses={204: OpenApiResponse(description="Sesión cerrada"), 400: None, 401: ERROR},
        tags=["Cuentas"],
    )
    def post(self, request):
        entrada = CerrarSesionSerializer(data=request.data, context={"request": request})
        entrada.is_valid(raise_exception=True)
        entrada.validated_data["refresh"].blacklist()
        return Response(status=status.HTTP_204_NO_CONTENT)


class YoView(APIView):
    permite_cambio_de_clave_pendiente = True

    @extend_schema(
        summary="Datos de la cuenta del token",
        responses={200: UsuarioSerializer, 401: ERROR},
        tags=["Cuentas"],
    )
    def get(self, request):
        return Response(datos_usuario(request.user))


class CambiarClaveView(APIView):
    # La única salida para una cuenta con cambio de clave obligatorio (E1C-138).
    permite_cambio_de_clave_pendiente = True
    # Con un token robado no se puede probar claves actuales sin límite.
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "cambiar_clave"

    @extend_schema(
        summary="Cambiar la clave",
        description=(
            "Pide la clave actual y valida la nueva con las reglas de Django. Cierra todas "
            "las sesiones de la cuenta y devuelve tokens nuevos."
        ),
        request=CambiarClaveSerializer,
        responses={200: TokensSerializer, 400: None, 401: ERROR, 429: ERROR},
        tags=["Cuentas"],
    )
    def post(self, request):
        entrada = CambiarClaveSerializer(data=request.data, context={"request": request})
        entrada.is_valid(raise_exception=True)
        usuario = request.user
        era_obligatorio = debe_cambiar_clave(usuario)
        with transaction.atomic():
            usuario.set_password(entrada.validated_data["clave_nueva"])
            usuario.save(update_fields=["password"])
            invalidar_refrescos(usuario)
            Perfil.objects.update_or_create(usuario=usuario, defaults={"debe_cambiar_clave": False})
            # Nunca la clave: solo que cambió y si era el cambio obligatorio.
            registrar(
                Accion.CLAVE_CAMBIADA,
                request=request,
                objeto=usuario,
                nuevo={"cambio_obligatorio": era_obligatorio},
            )
        # Los accesos anteriores ya no sirven (CHECK_REVOKE_TOKEN): se entregan unos nuevos.
        return Response(tokens_para(usuario))
