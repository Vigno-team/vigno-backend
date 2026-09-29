"""Tests para el comando de ingesta de Excel de estaciones meteorológicas."""

import pytest
import openpyxl
import pytz
from django.core.management import call_command
from django.core.management.base import CommandError
from apps.clima.models import Estacion, MedicionHoraria
from apps.ingesta.models import RegistroCarga

@pytest.fixture
def excel_sintetico(tmp_path):

    # Crear un excel falso
    archivo = tmp_path / "datos_sinteticos.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "mensual"
    
    # Simular filas basura
    for i in range(4):
        ws.append([f"Basura {i}"])
        
    # Fila 5: Cabecera superior
    ws.append(["FECHA", "TEMPERATURA", "TEMPERATURA", "TEMPERATURA", "HUMEDAD RELATIVA", "RAD MAX", "VEL. MAX. VIENTO", "VEL. MAX. VIENTO", "PP"])
    # Fila 6: Cabecera inferior
    ws.append([None, "Media diaria", "Máxima", "Mínima", "H.R. Media (%)", "(W/m2)", "(m/s)", "Abejas", "(mm)"])
    # Fila 7: Vacía
    ws.append([])
    
    # Simular dats reales (A partir de la fila 8)
    # Dato normal, pero en el día del cambio de hora de Chile
    ws.append(["2025-09-07 00:00:00", 15.0, 20.0, 10.0, 50.0, 800.0, 5.0, 100, 0.0])
    # Fecha con hora 23:00 (error común en los Excel)
    ws.append(["2025-09-08 23:00:00", 16.0, 21.0, 11.0, 55.0, 810.0, 6.0, 120, 2.0])
    # Fecha inválida ("00:00" en vez de fecha)
    ws.append(["00:00", 12.0, 12.0, 12.0, 12.0, 12.0, 12.0, 12, 12.0])
    # Celda de temperatura vacia
    ws.append(["2025-09-10 00:00:00", None, 22.0, 12.0, 60.0, 820.0, 7.0, 130, 0.0])
    
    wb.save(archivo)
    return str(archivo)

@pytest.mark.django_db
def test_ingesta_exitosa_y_reglas_negocio(excel_sintetico):
    call_command('ingestar_excel', archivo=excel_sintetico, estacion="San Clemente")
    
    # Validar Trazabilidad de Carga y descarte de abejas
    carga = RegistroCarga.objects.first()
    assert carga.filas_leidas == 4
    assert carga.filas_rechazadas == 1
    assert carga.filas_aceptadas == 3
    assert "1 columnas de abejas" in carga.columnas_descartadas
    assert carga.formato_detectado == "B_2023_2026"
    
    # Validar que la celda vacia no botó el script y guardó el motivo correcto
    medicion_vacia = MedicionHoraria.objects.get(timestamp__date__day=10, variable="temperatura_media")
    assert medicion_vacia.valor is None
    assert "Dato en blanco" in medicion_vacia.motivo_nulo

    # Validar resolucion del cambio de hora
    tz = pytz.timezone("America/Santiago")
    
    medicion_cambio = MedicionHoraria.objects.filter(timestamp__date__day=7).first()
    hora_local_cambio = medicion_cambio.timestamp.astimezone(tz).hour
    assert hora_local_cambio == 12  # Ignoró el 00:00
    
    medicion_23hrs = MedicionHoraria.objects.filter(timestamp__date__day=8).first()
    hora_local_23hrs = medicion_23hrs.timestamp.astimezone(tz).hour
    assert hora_local_23hrs == 12  

@pytest.mark.django_db
def test_ingesta_idempotente_y_conflicto(excel_sintetico):
    # Correr el comando 2 veces seguidas
    call_command('ingestar_excel', archivo=excel_sintetico, estacion="San Clemente")
    call_command('ingestar_excel', archivo=excel_sintetico, estacion="San Clemente")
    
    cargas = RegistroCarga.objects.all().order_by('id')
    assert cargas.count() == 2
    
    # La primera vez se inserta todo nuevo
    assert cargas[0].registros_insertados > 0
    assert cargas[0].registros_actualizados == 0
    
    # La segunda vez no inserta nada nuevo
    assert cargas[1].registros_insertados == 0
    assert cargas[1].registros_actualizados > 0
    
    assert MedicionHoraria.objects.count() == 21

@pytest.mark.django_db
def test_falla_si_columna_falta_o_formato_desconocido(tmp_path):
    archivo = tmp_path / "datos_rotos.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "mensual"
    for i in range(4): ws.append([f"Basura {i}"])
    
    # Faltan la mitad de las columnas para forzar el error
    ws.append(["FECHA", "TEMPERATURA"])
    ws.append([None, "Media diaria"])
    ws.append([])
    ws.append(["2025-09-07 00:00:00", 15.0])
    wb.save(archivo)
    
    with pytest.raises(CommandError, match="no calza con ningun formato"):
        call_command('ingestar_excel', archivo=str(archivo), estacion="San Clemente")