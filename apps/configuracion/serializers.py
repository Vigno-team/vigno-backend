"""Forma de la marca en la API y validación del logo."""

from PIL import Image, UnidentifiedImageError
from rest_framework import serializers

from apps.configuracion.models import ConfiguracionInstancia

CAMPOS_COLOR = ("color_primario", "color_secundario", "color_acento", "color_fondo")
# Lo que se puede editar con PATCH; el logo va por su propia ruta.
CAMPOS_EDITABLES = (
    "nombre_organizacion",
    "nombre_sistema",
    *CAMPOS_COLOR,
    "tipografia",
    "texto_pie",
)

# Formato que detecta Pillow -> extensión con que se guarda. SVG no está: puede traer scripts.
FORMATOS_LOGO = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}
TAMANO_MAXIMO_LOGO = 1024 * 1024  # 1 MB
LADO_MAXIMO_LOGO = 4096  # px; un logo no necesita más


class ConfiguracionSerializer(serializers.ModelSerializer):
    """Lectura (GET) y edición parcial (PATCH). El logo sale como URL absoluta o null."""

    class Meta:
        model = ConfiguracionInstancia
        fields = (*CAMPOS_EDITABLES, "logo", "actualizado")
        read_only_fields = ("logo", "actualizado")

    def validate(self, attrs):
        # Un mismo color siempre igual en la bitácora y en el ETag: #1f4e79 -> #1F4E79.
        for campo in CAMPOS_COLOR:
            if campo in attrs:
                attrs[campo] = attrs[campo].upper()
        return attrs


class LogoSerializer(serializers.Serializer):
    logo = serializers.FileField()

    def validate_logo(self, archivo):
        if archivo.size > TAMANO_MAXIMO_LOGO:
            raise serializers.ValidationError("El logo puede pesar hasta 1 MB.")
        try:
            # formats limita los decodificadores: Pillow ni intenta leer otros tipos.
            with Image.open(archivo, formats=list(FORMATOS_LOGO)) as imagen:
                formato = imagen.format
                ancho, alto = imagen.size
                imagen.verify()  # recorre el archivo: detecta imágenes truncadas o dañadas
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError) as e:
            raise serializers.ValidationError(
                "El archivo no es una imagen PNG, JPG o WebP válida."
            ) from e
        if ancho > LADO_MAXIMO_LOGO or alto > LADO_MAXIMO_LOGO:
            raise serializers.ValidationError(
                f"El logo puede medir hasta {LADO_MAXIMO_LOGO} × {LADO_MAXIMO_LOGO} px."
            )
        archivo.seek(0)  # verify() dejó el archivo leído hasta el final
        # El nombre del cliente no se usa: la extensión sale del contenido real.
        archivo.name = f"logo.{FORMATOS_LOGO[formato]}"
        return archivo
