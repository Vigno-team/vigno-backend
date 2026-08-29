"""Verifica que el entorno levanta y la base de datos responde."""

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
