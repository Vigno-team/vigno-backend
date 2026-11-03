"""Comprueba los settings reales en un proceso nuevo, sin heredar Django de pytest."""

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def entorno(**cambios):
    return {
        **os.environ,
        "DJANGO_SETTINGS_MODULE": "vigno.settings.production",
        "SECRET_KEY": secrets.token_urlsafe(48),
        "POSTGRES_PASSWORD": secrets.token_urlsafe(48),
        "ALLOWED_HOSTS": "localhost,testserver",
        "ADMIN_HABILITADO": "False",
        "DOCS_HABILITADOS": "False",
        "SESSION_COOKIE_SECURE": "True",
        "CSRF_COOKIE_SECURE": "True",
        "SECURE_HSTS_SECONDS": "3600",
        **cambios,
    }


def test_check_deploy_sin_advertencias():
    resultado = subprocess.run(
        [sys.executable, "manage.py", "check", "--deploy", "--fail-level", "WARNING"],
        cwd=RAIZ,
        env=entorno(),
        capture_output=True,
        text=True,
    )
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr


@pytest.mark.parametrize("habilitado", ["False", "True"])
def test_admin_y_documentacion_solo_con_habilitacion_explicita(habilitado):
    codigo = """
import json
import django
django.setup()
from django.urls import resolve, Resolver404
encontradas = []
for ruta in ('/admin/', '/api/docs/', '/api/schema/'):
    try:
        resolve(ruta)
    except Resolver404:
        encontradas.append(False)
    else:
        encontradas.append(True)
print(json.dumps(encontradas))
"""
    resultado = subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=RAIZ,
        env=entorno(ADMIN_HABILITADO=habilitado, DOCS_HABILITADOS=habilitado),
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(resultado.stdout) == [habilitado == "True"] * 3


def test_produccion_redirige_http_y_protege_respuestas_https():
    codigo = """
import json
import django
django.setup()
from django.conf import settings
from django.test import Client
cliente = Client()
http = cliente.get('/api/docs/')
https = cliente.get('/api/docs/', HTTP_X_FORWARDED_PROTO='https')
print(json.dumps({
    'http': http.status_code, 'destino': http['Location'],
    'https': https.status_code, 'hsts': https['Strict-Transport-Security'],
    'session': settings.SESSION_COOKIE_SECURE, 'csrf': settings.CSRF_COOKIE_SECURE,
    'debug': settings.DEBUG,
}))
"""
    resultado = subprocess.run(
        [sys.executable, "-c", codigo],
        cwd=RAIZ,
        env=entorno(DEBUG="True"),
        capture_output=True,
        text=True,
        check=True,
    )
    datos = json.loads(resultado.stdout)
    assert datos["http"] == 301
    assert datos["destino"] == "https://testserver/api/docs/"
    assert datos["https"] == 404
    assert "max-age=3600" in datos["hsts"]
    assert datos["session"] and datos["csrf"] and not datos["debug"]
