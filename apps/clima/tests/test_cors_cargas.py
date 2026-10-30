import pytest
from rest_framework.test import APIClient


@pytest.mark.parametrize("ruta", ["cargas", "estaciones", "correcciones"])
def test_vite_puede_enviar_clave_privada_sin_exponerla(ruta, settings):
    settings.CORS_ALLOWED_ORIGINS = ["http://localhost:5173"]
    respuesta = APIClient().options(
        f"/api/v1/{ruta}",
        HTTP_ORIGIN="http://localhost:5173",
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="POST",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="x-api-key,content-type",
    )
    assert respuesta.status_code == 200
    assert respuesta["Access-Control-Allow-Origin"] == "http://localhost:5173"
    assert "x-api-key" in respuesta["Access-Control-Allow-Headers"]
    assert "content-type" in respuesta["Access-Control-Allow-Headers"]
    assert "POST" in respuesta["Access-Control-Allow-Methods"]
    assert "X-Api-Key" not in respuesta
