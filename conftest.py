"""Los tests históricos cargan explícitamente su instancia, no desde migraciones."""

from pathlib import Path

import pytest
from django.core.management import call_command

from vigno.instancia import cargar_configuracion

CARPETA = Path(__file__).parent / "config/instancias/casas-patronales"


@pytest.fixture(scope="session")
def django_db_setup(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock():
        call_command("cargar_instancia", str(CARPETA), sin_activar=True, verbosity=0)


@pytest.fixture(autouse=True)
def instancia_historica(settings):
    settings.INSTANCIA = cargar_configuracion(CARPETA / "instancia.json")
    settings.TIME_ZONE = settings.INSTANCIA["zona_horaria"]
