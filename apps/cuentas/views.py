"""Rutas de /api/v1/auth (E1C-64). Solo el login y el refresco funcionan sin token."""

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from drf_spectacular.utils import OpenApiResponse, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenViewBase

from apps.auditoria.registro import Accion, instantanea_usuario, registrar
from apps.cuentas.models import Perfil, debe_cambiar_clave
from apps.cuentas.permisos import EsAdministrador
from apps.cuentas.roles import ADMINISTRADOR, ROLES, asignar_rol, rol_de
from apps.cuentas.serializers import (
    CambiarClaveSerializer,
    CerrarSesionSerializer,
    CrearUsuarioSerializer,
    EditarUsuarioSerializer,
    LoginSerializer,
    RefrescoSerializer,
    RestablecerClaveSerializer,
    UsuarioAdminSerializer,
    datos_usuario,
    invalidar_refrescos,
    tokens_para,
)

User = get_user_model()


def _administradores_activos():
    return (
        User.objects.filter(is_active=True)
        .filter(Q(is_superuser=True) | Q(groups__name=ADMINISTRADOR))
        .distinct()
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


class UsuariosView(APIView):
    """Listado y creación de usuarios. Solo administradores."""

    permission_classes = [EsAdministrador]

    @extend_schema(
        summary="Listar usuarios",
        description="Permite filtrar por rol y estado activo.",
        responses={200: UsuarioAdminSerializer(many=True)},
        tags=["Usuarios"],
    )
    def get(self, request):
        usuarios = User.objects.all().order_by("id")

        rol = request.query_params.get("rol")
        activo = request.query_params.get("activo")

        if rol:
            if rol not in ROLES:
                return Response(
                    {"rol": "El rol indicado no es válido."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            usuarios = [usuario for usuario in usuarios if rol_de(usuario) == rol]

        if activo is not None:
            if activo.lower() not in ("true", "false"):
                return Response(
                    {"activo": "Debe ser true o false."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            usuarios = [
                usuario for usuario in usuarios if usuario.is_active == (activo.lower() == "true")
            ]

        return Response(UsuarioAdminSerializer(usuarios, many=True).data)

    @extend_schema(
        summary="Crear usuario",
        request=CrearUsuarioSerializer,
        responses={201: UsuarioAdminSerializer, 400: None},
        tags=["Usuarios"],
    )
    def post(self, request):
        entrada = CrearUsuarioSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        datos = entrada.validated_data

        with transaction.atomic():
            usuario = User.objects.create_user(
                username=datos["email"],
                email=datos["email"],
                first_name=datos["nombre"],
                password=datos["clave_temporal"],
            )
            asignar_rol(usuario, datos["rol"])

            Perfil.objects.update_or_create(
                usuario=usuario,
                defaults={"debe_cambiar_clave": True},
            )

            nuevo = instantanea_usuario(usuario)
            nuevo["debe_cambiar_clave"] = True

            registrar(
                Accion.USUARIO_ALTA,
                request=request,
                objeto=usuario,
                nuevo=nuevo,
            )

        return Response(
            UsuarioAdminSerializer(usuario).data,
            status=status.HTTP_201_CREATED,
        )


class UsuarioDetalleView(APIView):
    """Consulta, edición y baja lógica de un usuario."""

    permission_classes = [EsAdministrador]

    def obtener_usuario(self, pk):
        return User.objects.filter(pk=pk).first()

    @extend_schema(
        summary="Consultar usuario",
        responses={200: UsuarioAdminSerializer, 404: None},
        tags=["Usuarios"],
    )
    def get(self, request, pk):
        usuario = self.obtener_usuario(pk)
        if usuario is None:
            return Response(
                {"detail": "Usuario no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(UsuarioAdminSerializer(usuario).data)

    @extend_schema(
        summary="Editar usuario",
        request=EditarUsuarioSerializer,
        responses={200: UsuarioAdminSerializer, 400: None, 404: None},
        tags=["Usuarios"],
    )
    def patch(self, request, pk):
        usuario = self.obtener_usuario(pk)
        if usuario is None:
            return Response(
                {"detail": "Usuario no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        entrada = EditarUsuarioSerializer(
            usuario,
            data=request.data,
            partial=True,
        )
        entrada.is_valid(raise_exception=True)
        cambios = entrada.validated_data

        if usuario.pk == request.user.pk:
            if cambios.get("activo") is False:
                return Response(
                    {"detail": "No puedes desactivar tu propia cuenta."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if cambios.get("rol") is not None and cambios["rol"] != ADMINISTRADOR:
                return Response(
                    {"detail": "No puedes quitarte tu propio rol de administrador."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        with transaction.atomic():
            anterior = instantanea_usuario(usuario)
            pierde_administracion = (
                usuario.is_active
                and rol_de(usuario) == ADMINISTRADOR
                and (
                    cambios.get("activo") is False
                    or cambios.get("rol", ADMINISTRADOR) != ADMINISTRADOR
                )
            )

            if pierde_administracion:
                administradores = list(
                    _administradores_activos().select_for_update().values_list("pk", flat=True)
                )

                if len(administradores) <= 1:
                    return Response(
                        {
                            "detail": (
                                "No puedes quitar la administración "
                                "al último administrador activo."
                            )
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            anterior["debe_cambiar_clave"] = debe_cambiar_clave(usuario)

            if "nombre" in cambios:
                usuario.first_name = cambios["nombre"]
            if "email" in cambios:
                usuario.email = cambios["email"]
                usuario.username = cambios["email"]
            if "activo" in cambios:
                usuario.is_active = cambios["activo"]

            usuario.save()

            if "rol" in cambios:
                asignar_rol(usuario, cambios["rol"])

            nuevo = instantanea_usuario(usuario)
            nuevo["debe_cambiar_clave"] = debe_cambiar_clave(usuario)

            if anterior != nuevo:
                accion = (
                    Accion.USUARIO_BAJA
                    if anterior["is_active"] and not nuevo["is_active"]
                    else Accion.USUARIO_EDICION
                )

                registrar(
                    accion,
                    request=request,
                    objeto=usuario,
                    anterior=anterior,
                    nuevo=nuevo,
                )

        return Response(UsuarioAdminSerializer(usuario).data)

    @extend_schema(
        summary="Desactivar usuario",
        responses={204: None, 400: None, 404: None},
        tags=["Usuarios"],
    )
    def delete(self, request, pk):
        with transaction.atomic():
            usuario = User.objects.filter(pk=pk).first()

            if usuario is None:
                return Response(
                    {"detail": "Usuario no encontrado."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            if usuario.pk == request.user.pk:
                return Response(
                    {"detail": "No puedes desactivar tu propia cuenta."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if usuario.is_active and rol_de(usuario) == ADMINISTRADOR:
                administradores = list(
                    _administradores_activos()
                    .select_for_update()
                    .order_by("pk")
                    .values_list("pk", flat=True)
                )

                if len(administradores) <= 1:
                    return Response(
                        {"detail": ("No puedes desactivar al último " "administrador activo.")},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            anterior = instantanea_usuario(usuario)
            anterior["debe_cambiar_clave"] = debe_cambiar_clave(usuario)

            usuario.is_active = False
            usuario.save(update_fields=["is_active"])

            nuevo = instantanea_usuario(usuario)
            nuevo["debe_cambiar_clave"] = debe_cambiar_clave(usuario)

            registrar(
                Accion.USUARIO_BAJA,
                request=request,
                objeto=usuario,
                anterior=anterior,
                nuevo=nuevo,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)


class RestablecerClaveView(APIView):
    """Restablecimiento de contraseña por un administrador."""

    permission_classes = [EsAdministrador]

    @extend_schema(
        summary="Restablecer contraseña de usuario",
        request=RestablecerClaveSerializer,
        responses={204: None, 400: None, 404: None},
        tags=["Usuarios"],
    )
    def post(self, request, pk):
        usuario = User.objects.filter(pk=pk).first()

        if usuario is None:
            return Response(
                {"detail": "Usuario no encontrado."},
                status=status.HTTP_404_NOT_FOUND,
            )

        entrada = RestablecerClaveSerializer(
            data=request.data,
            context={"usuario_objetivo": usuario},
        )
        entrada.is_valid(raise_exception=True)

        with transaction.atomic():
            usuario.set_password(entrada.validated_data["clave_temporal"])
            usuario.save(update_fields=["password"])

            invalidar_refrescos(usuario)

            Perfil.objects.update_or_create(
                usuario=usuario,
                defaults={"debe_cambiar_clave": True},
            )

            nuevo = instantanea_usuario(usuario)
            nuevo["debe_cambiar_clave"] = True
            nuevo["restablecimiento_administrativo"] = True

            registrar(
                Accion.CLAVE_CAMBIADA,
                request=request,
                objeto=usuario,
                nuevo=nuevo,
            )

        return Response(status=status.HTTP_204_NO_CONTENT)
