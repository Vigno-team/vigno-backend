from datetime import date
import pandas as pd
import pytest
from apps.clima.models import ConfiguracionCalidad, ResumenDiario
from apps.clima.services import derivar_resumenes_diarios, consultar_completitud_periodo

@pytest.mark.django_db
def test_procesar_frecuencia_diaria():
    """Aqui se verifica que los datos que ya vienen agregados por día se guarden directo."""
    df = pd.DataFrame({
        "estacion": ["San Clemente"],
        "timestamp": ["2026-03-01"],
        "temperatura_maxima": [30.5],
        "temperatura_minima": [10.0],
        "temperatura_media": [20.2],
        "frecuencia": ["D"]
    })
    
    resultados = derivar_resumenes_diarios(df)
    
    assert len(resultados) == 1
    assert resultados[0].amplitud_termica == 20.5
    assert resultados[0].origen == "D"
    assert resultados[0].horas_validas is None


@pytest.mark.django_db
def test_procesar_frecuencia_horaria():
    """Aqui se verifica que los datos horarios se agrupen y calculen matemáticamente."""
    df = pd.DataFrame({
        "estacion": ["El Arenal", "El Arenal"],
        "timestamp": ["2026-03-02 10:00:00", "2026-03-02 11:00:00"],
        "temperatura_media": [15.0, 25.0],
        "frecuencia": ["H", "H"]
    })
    
    resultados = derivar_resumenes_diarios(df)
    
    assert len(resultados) == 1
    assert resultados[0].tmax == 25.0
    assert resultados[0].tmin == 15.0
    assert resultados[0].tmedia == 20.0
    assert resultados[0].amplitud_termica == 10.0
    assert resultados[0].origen == "H"
    assert resultados[0].horas_validas == 2


@pytest.mark.django_db
def test_completitud_periodo_bajo_umbral():
    """Aqui se verifica que un periodo con pocos dias validos se marque como no confiable."""
    ConfiguracionCalidad.objects.create(clave="umbral_completitud_pct", umbral_pct=80.0)
    
    # Se inserta 1 dato diario y 1 dato horario ya calculado en un rango de 10 días
    ResumenDiario.objects.create(estacion="El Arenal", fecha=date(2026, 3, 1), tmedia=20.0, origen="D")
    ResumenDiario.objects.create(estacion="El Arenal", fecha=date(2026, 3, 2), tmedia=22.0, origen="H", horas_validas=24)
    
    resultado = consultar_completitud_periodo("El Arenal", date(2026, 3, 1), date(2026, 3, 10))
    
    assert resultado["dias_esperados"] == 10
    assert resultado["dias_validos"] == 2
    assert resultado["completitud_pct"] == 20.0
    assert resultado["es_confiable"] is False