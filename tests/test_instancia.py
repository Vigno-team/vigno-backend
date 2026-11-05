import copy
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from psycopg2 import sql

from apps.clima.models import Estacion
from apps.clima.temporadas import rango_invernal, rango_temporada, rango_winkler, temporada_de
from vigno.instancia import cargar_configuracion, validar_configuracion

RAIZ = Path(__file__).resolve().parents[1]
CP = RAIZ / "config/instancias/casas-patronales"
NORTE = RAIZ / "config/instancias/ejemplo-norte"


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("zona_horaria", "Zona/Inventada"),
        ("json_salida", "../datos.json"),
        ("json_salida", "C:\\datos.json"),
        ("organizacion", {"nombre": ""}),
        ("version", True),
        ("limites_geograficos", {"latitud": [90, -90], "longitud": [-180, 180]}),
    ],
)
def test_configuracion_invalida_se_rechaza(campo, valor):
    datos = cargar_configuracion(NORTE / "instancia.json")
    datos[campo] = valor
    with pytest.raises(ImproperlyConfigured):
        validar_configuracion(datos)


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("mes_inicio_temporada", 0),
        ("mes_inicio_anio_agricola", True),
        ("meses_invierno", [12, 2]),
        ("meses_invierno", [1, 1]),
        ("desfase_anio_invierno", 5),
        ("etapas_crecimiento", []),
    ],
)
def test_calendario_invalido_no_arranca(campo, valor):
    datos = cargar_configuracion(NORTE / "instancia.json")
    datos["calendario"][campo] = valor
    with pytest.raises(ImproperlyConfigured):
        validar_configuracion(datos)


def test_etapas_solapadas_y_fechas_imposibles_se_rechazan():
    datos = cargar_configuracion(NORTE / "instancia.json")
    solapadas = copy.deepcopy(datos)
    solapadas["calendario"]["etapas_crecimiento"][1]["inicio"] = [5, 1]
    with pytest.raises(ImproperlyConfigured, match="solaparse"):
        validar_configuracion(solapadas)
    datos["calendario"]["ventanas_indices"]["winkler"]["fin"] = [4, 31]
    with pytest.raises(ImproperlyConfigured, match="inválido"):
        validar_configuracion(datos)


def test_invierno_norte_cruza_diciembre_y_usa_febrero_bisiesto(settings):
    from datetime import date

    settings.INSTANCIA = cargar_configuracion(NORTE / "instancia.json")
    assert temporada_de(date(2024, 1, 1)) == "2024-2025"
    assert rango_temporada("2024-2025") == (date(2024, 1, 1), date(2024, 12, 31))
    assert rango_invernal("2024-2025") == (date(2023, 12, 1), date(2024, 2, 29))
    assert rango_winkler("2024-2025") == (date(2024, 4, 1), date(2024, 10, 31))
    assert rango_invernal("2025-2026")[1] == date(2025, 2, 28)


@pytest.mark.django_db
def test_carga_idempotente_activa_configuracion_sin_borrar_estaciones(settings, tmp_path):
    settings.INSTANCIA_CONFIG = tmp_path / "instancia.json"
    Estacion.objects.create(nombre="Agregada por el cliente", codigo="cliente-01")
    call_command("cargar_instancia", str(CP))
    primero = list(Estacion.objects.order_by("id").values())
    call_command("cargar_instancia", str(CP))
    assert list(Estacion.objects.order_by("id").values()) == primero
    assert cargar_configuracion(settings.INSTANCIA_CONFIG) == cargar_configuracion(
        CP / "instancia.json"
    )


@pytest.mark.django_db
def test_instancia_invalida_no_carga_parcialmente(settings, tmp_path):
    settings.INSTANCIA_CONFIG = tmp_path / "activa.json"
    (tmp_path / "instancia.json").write_text(
        (CP / "instancia.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    filas = json.loads((CP / "estaciones.json").read_text(encoding="utf-8"))
    filas[0]["propietario"] = "No se debe guardar"
    filas[1]["codigo"] = filas[0]["codigo"]
    (tmp_path / "estaciones.json").write_text(json.dumps(filas), encoding="utf-8")
    antes = list(Estacion.objects.order_by("id").values())
    with pytest.raises(CommandError, match="repetidos"):
        call_command("cargar_instancia", str(tmp_path))
    assert list(Estacion.objects.order_by("id").values()) == antes
    assert not settings.INSTANCIA_CONFIG.exists()


@pytest.fixture
def base_nueva(tmp_path, transactional_db):
    """BD desechable independiente: prueba migraciones reales desde cero."""
    nombre = "test_instancia_" + uuid.uuid4().hex
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(nombre)))
    env = {
        **os.environ,
        "POSTGRES_DB": nombre,
        "DJANGO_SETTINGS_MODULE": "vigno.settings.development",
        "INSTANCIA_CONFIG": str(NORTE / "instancia.json"),
        "DATOS_DIR": str(tmp_path / "datos"),
        "ALLOWED_HOSTS": "testserver,localhost,127.0.0.1",
        "API_LECTURA_PUBLICA": "True",
    }
    try:
        yield env
    finally:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(nombre)))


def ejecutar(env, *args):
    proceso = subprocess.run(
        [sys.executable, *args], cwd=RAIZ, env=env, capture_output=True, text=True
    )
    assert proceso.returncode == 0, proceso.stdout + proceso.stderr
    return proceso.stdout


def test_arranque_rechaza_configuracion_explicita_invalida(tmp_path):
    archivo = tmp_path / "instancia.json"
    archivo.write_text('{"version": 1}', encoding="utf-8")
    proceso = subprocess.run(
        [sys.executable, "manage.py", "check"],
        cwd=RAIZ,
        env={**os.environ, "INSTANCIA_CONFIG": str(archivo)},
        capture_output=True,
        text=True,
    )
    assert proceso.returncode != 0
    assert "instancia.json: raíz" in proceso.stderr


def test_instalacion_nueva_y_flujo_completo_del_norte(base_nueva):
    ejecutar(base_nueva, "manage.py", "migrate", "--noinput")
    codigo = """
import django
django.setup()
import io, json, tempfile
from datetime import date, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from django.conf import settings
from django.core.management import call_command
from django.test import Client
from apps.clima.models import Estacion, MedicionHoraria, ResumenDiario, IndiceClimatico
from apps.clima.tests.test_ingestar_excel import crear_excel, fila
assert Estacion.objects.count() == 0, 'Una base nueva debe partir vacía'
assert settings.TIME_ZONE == 'Europe/Paris'
assert settings.SPECTACULAR_SETTINGS['TITLE'] == 'Viña Norte API'
call_command('cargar_instancia', str(settings.BASE_DIR/'config/instancias/ejemplo-norte'), sin_activar=True)
assert Estacion.objects.count() == 1
with tempfile.TemporaryDirectory() as carpeta:
    filas = []
    fecha = date(2023,12,1)
    while fecha <= date(2024,12,31):
        registro = fila(fecha.isoformat(),20)
        registro[2] = 30
        registro[-1] = 1
        filas.append(registro)
        fecha += timedelta(days=1)
    archivo = crear_excel(Path(carpeta)/'historico.xlsx',filas)
    call_command('ingestar_excel',archivo=archivo,estacion='Estación Norte')
    call_command('actualizar_todo',sin_satelite=True)
assert ResumenDiario.objects.count() == 397
medicion = MedicionHoraria.objects.filter(variable='temperatura_media').earliest('timestamp')
assert medicion.timestamp.astimezone(ZoneInfo('Europe/Paris')).hour == 12
winkler = IndiceClimatico.objects.get(temporada='2024-2025',indice='Winkler')
assert winkler.valor == 2140 and winkler.confiable
assert winkler.version_calculo == 'winkler-v1_base10_0401-1031'
salida = settings.DATOS_DIR/settings.INSTANCIA['json_salida']
publicado = json.loads(salida.read_text())
assert publicado['estaciones'][0]['id'] == 'norte-01'
ficha = next(f for f in publicado['ficha_temporada'] if f['temporada']=='2024-2025')
assert ficha['lluvia_invernal']['acumulado_mm'] == 91
assert ficha['lluvia_invernal']['calidad_dato']['confiable']
api = Client()
assert api.get('/api/v1/datos').json() == publicado
assert api.get('/api/health/').json()['servicio'] == 'Viña Norte'
# Repetir catálogo y migraciones no elimina las mediciones de una base ya usada.
cantidad = MedicionHoraria.objects.count()
call_command('cargar_instancia', str(settings.BASE_DIR/'config/instancias/ejemplo-norte'), sin_activar=True)
call_command('migrate',verbosity=0)
assert MedicionHoraria.objects.count() == cantidad
assert Estacion.objects.count() == 1
print('NORTE_OK')
"""
    assert "NORTE_OK" in ejecutar(base_nueva, "-c", codigo)
