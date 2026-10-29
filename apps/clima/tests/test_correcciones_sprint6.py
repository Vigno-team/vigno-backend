import pytest
from apps.clima.models import MedicionHoraria, ResumenDiario

@pytest.mark.django_db
def test_excel_vacio_no_pisa_correccion():
    pass

@pytest.mark.django_db
def test_excel_valido_reemplaza_correccion():
    pass

@pytest.mark.django_db
def test_resumen_diario_marca_corregido_a_mano():
    pass
