import pytest
from rest_framework.test import APIClient


@pytest.mark.parametrize("ruta", ["cargas", "estaciones", "correcciones", "auth/token"])
def test_vite_puede_enviar_el_token_en_authorization(ruta, settings):
    settings.CORS_ALLOWED_ORIGINS = ["http://localhost:5173"]
    respuesta = APIClient().options(
        f"/api/v1/{ruta}",
        HTTP_ORIGIN="http://localhost:5173",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,content-type",
    )
    assert respuesta.status_code == 200
    assert respuesta["Access-Control-Allow-Origin"] == "http://localhost:5173"
    permitidas = respuesta["Access-Control-Allow-Headers"]
    assert "authorization" in permitidas
    assert "content-type" in permitidas
    # E1C-64: la clave compartida se retiró
    assert "x-api-key" not in permitidas
    assert "POST" in respuesta["Access-Control-Allow-Methods"]


def test_otro_origen_no_recibe_permiso_cors(settings):
    settings.CORS_ALLOWED_ORIGINS = ["http://localhost:5173"]
    respuesta = APIClient().options(
        "/api/v1/auth/token",
        HTTP_ORIGIN="https://sitio-ajeno.example",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="authorization,content-type",
    )
    assert "Access-Control-Allow-Origin" not in respuesta
