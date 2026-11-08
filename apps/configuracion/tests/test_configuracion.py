"""marca de la instancia. Lectura pública; edición solo del administrador."""

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from PIL import Image
from rest_framework.test import APIClient

from apps.auditoria.models import RegistroAuditoria
from apps.configuracion.models import ConfiguracionInstancia

pytestmark = pytest.mark.django_db

URL = "/api/v1/configuracion"
URL_LOGO = "/api/v1/configuracion/logo"
Accion = RegistroAuditoria.Accion
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


@pytest.fixture(autouse=True)
def media_temporal(settings, tmp_path):
    # Cada test guarda sus logos en una carpeta propia que pytest borra después:
    # nunca se escribe en el media/ real del proyecto.
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


def imagen(formato="PNG", tamano=(8, 8)) -> bytes:
    """Una imagen real, generada en memoria."""
    buffer = io.BytesIO()
    Image.new("RGB", tamano, "#1F4E79").save(buffer, format=formato)
    return buffer.getvalue()


def subir(cliente, contenido, nombre="logo.png"):
    return cliente.put(
        URL_LOGO, {"logo": SimpleUploadedFile(nombre, contenido)}, format="multipart"
    )


def test_la_lectura_es_publica_y_parte_de_instancia_json(settings):
    # Aunque las lecturas del dashboard pidan token, la marca no: la necesita el login.
    settings.API_LECTURA_PUBLICA = False

    respuesta = APIClient().get(URL)

    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["nombre_organizacion"] == settings.INSTANCIA["organizacion"]["nombre"]
    assert datos["nombre_sistema"] == settings.INSTANCIA["organizacion"]["nombre_corto"]
    assert datos["logo"] is None
    assert datos["color_primario"] == "#1F4E79"
    assert respuesta["Cache-Control"] == "no-cache"
    assert respuesta["ETag"].startswith('W/"')


def test_un_token_vencido_no_impide_leer():
    cliente = APIClient()
    cliente.credentials(HTTP_AUTHORIZATION="Bearer token-vencido-o-inventado")

    assert cliente.get(URL).status_code == 200


def test_el_etag_da_304_hasta_que_la_marca_cambia(cliente_admin):
    cliente = APIClient()
    etag = cliente.get(URL)["ETag"]

    assert cliente.get(URL, HTTP_IF_NONE_MATCH=etag).status_code == 304

    cliente_admin.patch(URL, {"color_acento": "#FF8800"}, format="json")
    respuesta = cliente.get(URL, HTTP_IF_NONE_MATCH=etag)

    assert respuesta.status_code == 200
    assert respuesta["ETag"] != etag
    assert respuesta.json()["color_acento"] == "#FF8800"


@pytest.mark.parametrize(
    "fixture_cliente,codigo",
    [(None, 401), ("cliente_lector", 403), ("cliente_con_token", 403)],
    ids=["sin-token", "lector", "editor"],
)
def test_solo_el_administrador_edita(request, fixture_cliente, codigo):
    cliente = request.getfixturevalue(fixture_cliente) if fixture_cliente else APIClient()

    textos = cliente.patch(URL, {"nombre_sistema": "Otro"}, format="json")
    logo = subir(cliente, imagen())

    assert (textos.status_code, logo.status_code) == (codigo, codigo)
    assert ConfiguracionInstancia.actual().nombre_sistema != "Otro"
    assert not RegistroAuditoria.objects.filter(
        accion__in=[Accion.MARCA_EDICION, Accion.LOGO_EDICION]
    ).exists()


def test_el_administrador_edita_y_queda_en_la_bitacora(cliente_admin):
    respuesta = cliente_admin.patch(
        URL, {"color_primario": "#aa0000", "texto_pie": "Hecho en el Valle"}, format="json"
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["color_primario"] == "#AA0000"  # se guarda en mayúsculas
    registro = RegistroAuditoria.objects.get(accion=Accion.MARCA_EDICION)
    assert registro.usuario.email == "admin@vigno.cl"
    assert registro.tipo_objeto == "configuracion.ConfiguracionInstancia"
    assert registro.valor_anterior["color_primario"] == "#1F4E79"
    assert registro.valor_nuevo["color_primario"] == "#AA0000"
    assert registro.valor_nuevo["texto_pie"] == "Hecho en el Valle"


def test_un_patch_sin_cambios_no_ensucia_la_bitacora(cliente_admin):
    respuesta = cliente_admin.patch(URL, {"tipografia": "system-ui"}, format="json")

    assert respuesta.status_code == 200
    assert not RegistroAuditoria.objects.filter(accion=Accion.MARCA_EDICION).exists()


@pytest.mark.parametrize("color", ["rojo", "#12345", "#1234567", "#GG0000", "1F4E79", ""])
def test_un_color_invalido_da_400(cliente_admin, color):
    respuesta = cliente_admin.patch(URL, {"color_fondo": color}, format="json")

    assert respuesta.status_code == 400
    assert "color_fondo" in respuesta.json()
    assert ConfiguracionInstancia.actual().color_fondo == "#FFFFFF"
    assert not RegistroAuditoria.objects.filter(accion=Accion.MARCA_EDICION).exists()


@pytest.mark.parametrize(
    "formato,extension", [("PNG", ".png"), ("JPEG", ".jpg"), ("WEBP", ".webp")]
)
def test_el_administrador_sube_el_logo(cliente_admin, media_temporal, formato, extension):
    # El nombre que manda el cliente no importa: la extensión sale del contenido.
    respuesta = subir(cliente_admin, imagen(formato), nombre="cualquier-nombre.bin")

    assert respuesta.status_code == 200
    url = respuesta.json()["logo"]
    assert url.startswith("http://testserver/media/marca/logo-")
    assert url.endswith(extension)
    guardado = ConfiguracionInstancia.actual().logo
    assert (media_temporal / guardado.name).is_file()
    registro = RegistroAuditoria.objects.get(accion=Accion.LOGO_EDICION)
    assert registro.valor_anterior["logo"] is None
    assert registro.valor_nuevo["logo"] == guardado.name


def test_al_reemplazar_el_logo_se_borra_el_anterior(
    cliente_admin, media_temporal, django_capture_on_commit_callbacks
):
    subir(cliente_admin, imagen("PNG"))
    primero = ConfiguracionInstancia.actual().logo.name

    with django_capture_on_commit_callbacks(execute=True):
        subir(cliente_admin, imagen("WEBP"))

    segundo = ConfiguracionInstancia.actual().logo.name
    assert segundo != primero
    assert not (media_temporal / primero).exists()
    assert (media_temporal / segundo).is_file()


@pytest.mark.parametrize(
    "contenido,nombre",
    [
        (b"esto no es una imagen", "logo.png"),
        (SVG, "logo.svg"),
        (SVG, "logo.png"),
        (imagen("GIF"), "logo.png"),
    ],
    ids=["texto", "svg", "svg-renombrado", "gif"],
)
def test_un_archivo_que_no_es_imagen_aceptada_da_400(
    cliente_admin, media_temporal, contenido, nombre
):
    respuesta = subir(cliente_admin, contenido, nombre)

    assert respuesta.status_code == 400
    assert "logo" in respuesta.json()
    assert not ConfiguracionInstancia.actual().logo
    assert not any(media_temporal.rglob("*.*"))
    assert not RegistroAuditoria.objects.filter(accion=Accion.LOGO_EDICION).exists()


def test_un_logo_de_mas_de_1_mb_da_400(cliente_admin):
    pesado = imagen("PNG") + b"\0" * (1024 * 1024)

    respuesta = subir(cliente_admin, pesado)

    assert respuesta.status_code == 400
    assert "1 MB" in respuesta.json()["logo"][0]


def test_un_logo_de_mas_de_4096_px_da_400(cliente_admin):
    respuesta = subir(cliente_admin, imagen("PNG", (4097, 1)))

    assert respuesta.status_code == 400


def test_hay_una_sola_configuracion():
    ConfiguracionInstancia.actual()
    # Guardar otra instancia no crea una segunda fila: save() fuerza pk=1 y la reemplaza.
    ConfiguracionInstancia(nombre_organizacion="Otra", nombre_sistema="Otra").save()

    assert ConfiguracionInstancia.objects.count() == 1
    # Ni saltándose save() (bulk_create no lo llama): lo impide la restricción de la base.
    with pytest.raises(IntegrityError), transaction.atomic():
        ConfiguracionInstancia.objects.bulk_create(
            [ConfiguracionInstancia(id=2, nombre_organizacion="X", nombre_sistema="X")]
        )
