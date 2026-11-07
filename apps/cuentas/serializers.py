"""Login con correo, refresco, cierre de sesión y cambio de clave (E1C-64)."""

import logging

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.models import update_last_login
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.serializers import TokenRefreshSerializer
from rest_framework_simplejwt.settings import api_settings
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.utils import get_md5_hash_password

from apps.auditoria.registro import Accion, registrar
from apps.cuentas.roles import rol_de

logger = logging.getLogger(__name__)

User = get_user_model()

# Una sola respuesta para correo inexistente, clave incorrecta y cuenta desactivada:
# así no se puede averiguar qué correos tienen cuenta.
CREDENCIALES_INVALIDAS = "Correo o contraseña incorrectos."
# Las claves largas se aceptan, pero sin límite alguien podría mandar megas para cansar al
# servidor con el hash.
LARGO_MAXIMO_CLAVE = 4096


def datos_usuario(usuario) -> dict:
    return {
        "id": usuario.pk,
        "nombre": usuario.get_full_name() or usuario.email,
        "email": usuario.email,
        "rol": rol_de(usuario),
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
