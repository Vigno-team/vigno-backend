"""Verifica que el entorno levanta y la base de datos responde."""

import json

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_health_check_responde_ok(client):
    response = client.get(reverse("health-check"))
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["base_datos"] == "conectada"


@pytest.mark.django_db
def test_schema_openapi_disponible(client):
    """El contrato de la API debe estar publicado para el equipo de frontend."""
    response = client.get("/api/schema/")
    assert response.status_code == 200


@pytest.mark.django_db
def test_health_informa_la_ultima_actualizacion(client, settings, tmp_path):
    settings.DATOS_DIR = tmp_path
    (tmp_path / "actualizacion.json").write_text(
        json.dumps({"generado": "2026-11-13T03:00:05-03:00", "ok": True, "pasos": []}),
        encoding="utf-8",
    )

    datos = client.get(reverse("health-check")).json()

    assert datos["ultima_actualizacion"] == "2026-11-13T03:00:05-03:00"
    assert datos["ultima_actualizacion_ok"] is True


@pytest.mark.django_db
@pytest.mark.parametrize("contenido", [None, "{no es json", "[]"])
def test_health_sin_actualizacion_legible_no_falla(client, settings, tmp_path, contenido):
    settings.DATOS_DIR = tmp_path
    if contenido is not None:
        (tmp_path / "actualizacion.json").write_text(contenido, encoding="utf-8")

    respuesta = client.get(reverse("health-check"))

    assert respuesta.status_code == 200
    assert respuesta.json()["ultima_actualizacion"] is None
    assert respuesta.json()["ultima_actualizacion_ok"] is None
