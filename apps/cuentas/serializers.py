"""Login con correo, refresco, cierre de sesión y cambio de clave (E1C-64)."""

import logging

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import update_last_login
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.http import urlsafe_base64_decode
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.utils import get_md5_hash_password

from apps.auditoria.registro import Accion, registrar
from apps.cuentas.models import debe_cambiar_clave
from apps.cuentas.roles import ROLES, rol_de

logger = logging.getLogger(__name__)

User = get_user_model()

# Una sola respuesta para correo inexistente, clave incorrecta y cuenta desactivada:
# así no se puede averiguar qué correos tienen cuenta.
CREDENCIALES_INVALIDAS = "Correo o contraseña incorrectos."
# Las claves largas se aceptan, pero sin límite alguien podría mandar megas para cansar al
# servidor con el hash.
LARGO_MAXIMO_CLAVE = 4096
# Enlace del correo de recuperación alterado, vencido o ya usado: el mismo mensaje,
# porque en los tres casos lo único que queda es pedir otro.
ENLACE_INVALIDO = "El enlace no es válido o ya venció. Pide uno nuevo."


def datos_usuario(usuario) -> dict:
    return {
        "id": usuario.pk,
        "nombre": usuario.get_full_name() or usuario.email,
        "email": usuario.email,
        "rol": rol_de(usuario),
        # E1C-138: con true, el frontend muestra la pantalla de cambio de clave.
        "debe_cambiar_clave": debe_cambiar_clave(usuario),
    }


def tokens_para(usuario) -> dict:
    refresco = RefreshToken.for_user(usuario)
    return {"access": str(refresco.access_token), "refresh": str(refresco)}


def invalidar_refrescos(usuario) -> None:
    """Pone en la lista negra todos los refrescos vigentes de la cuenta."""
    for token in OutstandingToken.objects.filter(user=usuario):
        BlacklistedToken.objects.get_or_create(token=token)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(
        max_length=LARGO_MAXIMO_CLAVE, trim_whitespace=False, write_only=True
    )

    def validate(self, attrs):
        request = self.context.get("request")
        correo = attrs["email"].strip()
        cuenta = User.objects.filter(email__iexact=correo).first()
        if cuenta is None:
            # Mismo costo que revisar una clave real: el tiempo de respuesta tampoco delata
            # si el correo existe.
            User().set_password(attrs["password"])
            usuario = None
        else:
            # authenticate() rechaza las cuentas desactivadas y avisa user_login_failed.
            usuario = authenticate(
                request,
                username=cuenta.get_username(),
                password=attrs["password"],
            )
        if usuario is None:
            logger.warning("Login fallido para %s", correo)
            # Sin usuario (nadie entró); el correo intentado sirve para detectar ataques.
            registrar(
                Accion.LOGIN_FALLIDO,
                request=request,
                tipo_objeto="auth.User",
                id_objeto=cuenta.pk if cuenta else "",
                nuevo={"email": correo},
            )
            raise AuthenticationFailed(CREDENCIALES_INVALIDAS, code="credenciales_invalidas")

        if api_settings.UPDATE_LAST_LOGIN:
            update_last_login(None, usuario)
        registrar(Accion.LOGIN_CORRECTO, request=request, usuario=usuario, objeto=usuario)
        return {**tokens_para(usuario), "usuario": datos_usuario(usuario)}


class RefrescoSerializer(TokenRefreshSerializer):
    def validate(self, attrs):
        refresco = RefreshToken(attrs["refresh"])  # firma, vencimiento y lista negra
        usuario = User.objects.filter(
            **{api_settings.USER_ID_FIELD: refresco.get(api_settings.USER_ID_CLAIM)}
        ).first()
        # simplejwt da error 500 si la cuenta ya no existe; aquí es un token inválido.
        if usuario is None or not api_settings.USER_AUTHENTICATION_RULE(usuario):
            raise InvalidToken("La cuenta del token ya no existe o está desactivada.")
        # Un refresco emitido antes de cambiar la clave no debe seguir dando acceso.
        if api_settings.CHECK_REVOKE_TOKEN and refresco.get(
            api_settings.REVOKE_TOKEN_CLAIM
        ) != get_md5_hash_password(usuario.password):
            raise InvalidToken("La clave cambió: vuelve a entrar.")
        return super().validate(attrs)


class CerrarSesionSerializer(serializers.Serializer):
    refresh = serializers.CharField()

    def validate_refresh(self, valor):
        try:
            refresco = RefreshToken(valor)
        except TokenError as error:
            raise serializers.ValidationError("Token de refresco inválido o vencido.") from error
        usuario = self.context["request"].user
        if str(refresco.get(api_settings.USER_ID_CLAIM)) != str(
            getattr(usuario, api_settings.USER_ID_FIELD)
        ):
            raise serializers.ValidationError("El token de refresco no es de esta cuenta.")
        return refresco


class CambiarClaveSerializer(serializers.Serializer):
    clave_actual = serializers.CharField(
        max_length=LARGO_MAXIMO_CLAVE, trim_whitespace=False, write_only=True
    )
    clave_nueva = serializers.CharField(
        max_length=LARGO_MAXIMO_CLAVE, trim_whitespace=False, write_only=True
    )

    def validate(self, attrs):
        usuario = self.context["request"].user
        if not usuario.check_password(attrs["clave_actual"]):
            raise serializers.ValidationError({"clave_actual": ["La clave actual no es correcta."]})
        if attrs["clave_nueva"] == attrs["clave_actual"]:
            raise serializers.ValidationError(
                {"clave_nueva": ["La clave nueva debe ser distinta de la actual."]}
            )
        try:
            validate_password(attrs["clave_nueva"], usuario)
        except DjangoValidationError as error:
            raise serializers.ValidationError({"clave_nueva": list(error.messages)}) from error
        return attrs


class UsuarioAdminSerializer(serializers.Serializer):
    """Datos de usuario visibles para la administración."""

    id = serializers.IntegerField(read_only=True)
    nombre = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True)
    rol = serializers.ChoiceField(choices=list(ROLES), allow_null=True, read_only=True)
    activo = serializers.BooleanField(source="is_active", read_only=True)
    debe_cambiar_clave = serializers.BooleanField(read_only=True)

    def to_representation(self, instance):
        return {
            "id": instance.pk,
            "nombre": instance.get_full_name() or instance.email,
            "email": instance.email,
            "rol": rol_de(instance),
            "activo": instance.is_active,
            "debe_cambiar_clave": debe_cambiar_clave(instance),
        }


class CrearUsuarioSerializer(serializers.Serializer):
    """Validación para crear una cuenta desde la administración."""

    nombre = serializers.CharField(max_length=150)
    email = serializers.EmailField(max_length=254)
    rol = serializers.ChoiceField(choices=list(ROLES))
    clave_temporal = serializers.CharField(
        max_length=LARGO_MAXIMO_CLAVE,
        trim_whitespace=False,
        write_only=True,
    )

    def validate_email(self, valor):
        correo = valor.strip().lower()

        if User.objects.filter(email__iexact=correo).exists():
            raise serializers.ValidationError("Ya existe una cuenta con ese correo.")

        if User.objects.filter(username__iexact=correo).exists():
            raise serializers.ValidationError("El correo ya está utilizado como nombre de usuario.")

        return correo

    def validate(self, attrs):
        usuario = User(
            username=attrs["email"],
            email=attrs["email"],
            first_name=attrs["nombre"],
        )

        try:
            validate_password(attrs["clave_temporal"], usuario)
        except DjangoValidationError as error:
            raise serializers.ValidationError({"clave_temporal": list(error.messages)}) from error

        return attrs


class EditarUsuarioSerializer(serializers.Serializer):
    """Validación para modificar los datos administrativos de una cuenta."""

    nombre = serializers.CharField(max_length=150, required=False)
    email = serializers.EmailField(max_length=254, required=False)
    rol = serializers.ChoiceField(choices=list(ROLES), required=False)
    activo = serializers.BooleanField(required=False)

    def validate_email(self, valor):
        correo = valor.strip().lower()
        existentes = User.objects.filter(email__iexact=correo).exclude(pk=self.instance.pk)

        if existentes.exists():
            raise serializers.ValidationError("Ya existe otra cuenta con ese correo.")

        usernames = User.objects.filter(username__iexact=correo).exclude(pk=self.instance.pk)

        if usernames.exists():
            raise serializers.ValidationError("El correo ya está utilizado como nombre de usuario.")

        return correo

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("Debes indicar al menos un campo para modificar.")
        return attrs


class RestablecerClaveSerializer(serializers.Serializer):
    """Validación de una nueva clave temporal."""

    clave_temporal = serializers.CharField(
        max_length=LARGO_MAXIMO_CLAVE,
        trim_whitespace=False,
        write_only=True,
    )

    def validate_clave_temporal(self, valor):
        try:
            validate_password(valor, self.context["usuario_objetivo"])
        except DjangoValidationError as error:
            raise serializers.ValidationError(list(error.messages)) from error

        return valor


class RecuperarClaveSerializer(serializers.Serializer):
    # Correo de la cuenta que olvidó su clave.

    email = serializers.EmailField(max_length=254)


def cuenta_del_enlace(uid, token):
    """La cuenta activa del enlace si el token sirve; None si está alterado, vencido o ya se usó.

    default_token_generator firma el token con la clave y el último ingreso de la cuenta: al
    cambiar la clave (o entrar) deja de servir, y vence según PASSWORD_RESET_TIMEOUT.
    """
    try:
        pk = urlsafe_base64_decode(uid).decode()
        usuario = User.objects.get(pk=pk, is_active=True)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist, DjangoValidationError):
        return None
    if not default_token_generator.check_token(usuario, token):
        return None
    return usuario


class RestablecerClavePorCorreoSerializer(serializers.Serializer):
    # Clave nueva elegida con el enlace del correo.

    uid = serializers.CharField(max_length=100)
    token = serializers.CharField(max_length=100)
    clave_nueva = serializers.CharField(
        max_length=LARGO_MAXIMO_CLAVE, trim_whitespace=False, write_only=True
    )

    def validate(self, attrs):
        usuario = cuenta_del_enlace(attrs["uid"], attrs["token"])
        if usuario is None:
            raise serializers.ValidationError({"token": [ENLACE_INVALIDO]})
        try:
            validate_password(attrs["clave_nueva"], usuario)
        except DjangoValidationError as error:
            raise serializers.ValidationError({"clave_nueva": list(error.messages)}) from error
        return {**attrs, "usuario": usuario}
