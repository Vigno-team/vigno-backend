"""E1C-121: misma métrica en persistencia, comparación, lluvia y API."""

from datetime import date, timedelta

import pytest

from apps.clima.comparacion import comparar_temporadas
from apps.clima.dias_criticos import calcular_dias_sobre_umbral
from apps.clima.indices import calcular_indices_temporada
from apps.clima.lluvia import lluvia_invernal
from apps.clima.metricas import valor_metrica
from apps.clima.models import Estacion, IndiceClimatico, ResumenDiario
from apps.clima.resultados import ficha_temporada
from apps.clima.temporadas import temporada_de

pytestmark = pytest.mark.django_db


@pytest.fixture
def estacion(settings):
    settings.UMBRAL_CALOR_C = 36
    est = Estacion.objects.create(nombre="Integración métricas", codigo="integracion", latitud=-41)
    inicio = date(2024, 10, 1)
    ResumenDiario.objects.bulk_create(
        [
            ResumenDiario(
                estacion=est,
                fecha=inicio + timedelta(days=i),
                temporada="2024-2025",
                tmedia=20,
                tmax=36 if i < 2 else 35.5,
                tmin=10,
            )
            for i in range(212)
        ]
    )
    # Fuera de la ventana del índice, pero sí dentro de la temporada anual de rachas.
    ResumenDiario.objects.create(
        estacion=est, fecha=date(2024, 9, 30), temporada="2024-2025", tmax=40
    )
    return est


@pytest.mark.parametrize(
    "metrica,nombre",
    [("winkler", "Winkler"), ("huglin", "Huglin"), ("dias_sobre_umbral", "DiasSobreUmbral")],
)
def test_persistencia_y_comparacion_reciben_el_mismo_resultado(estacion, metrica, nombre):
    calcular_indices_temporada(estacion, "2024-2025")
    guardado = IndiceClimatico.objects.get(estacion=estacion, temporada="2024-2025", indice=nombre)
    directo = valor_metrica(estacion, metrica, "2024-2025")
    comparacion = comparar_temporadas(estacion, "2024-2025", "2023-2024", hoy=date(2025, 7, 1))
    publicado = next(m["temporada"] for m in comparacion["metricas"] if m["metrica"] == metrica)
    assert publicado == directo
    assert guardado.valor == directo["valor"]
    assert guardado.confiable == directo["confiable"]
    assert guardado.dias_con_dato == directo["dias_con_dato"]
    assert guardado.dias_esperados == directo["dias_esperados"]


def test_ficha_y_dias_criticos_comparten_umbral_ventana_y_calidad(estacion):
    assert calcular_dias_sobre_umbral(estacion, "2024-2025") == 2
    ficha = ficha_temporada(estacion, "2024-2025")
    assert ficha["calor"]["dias_sobre_umbral"] == 2
    assert ficha["calor"]["umbral_c"] == 36
    assert ficha["calor"]["calidad_dato"]["completitud_pct"] == 100
    assert ficha["calor"]["calidad_dato"]["confiable"] is True
    assert ficha["calor"]["calidad_dato"]["version_calculo"] == "dias_umbral-v2_36c_1001-0430"


def test_solo_datos_fuera_de_la_ventana_no_inventan_cero(estacion):
    ResumenDiario.objects.filter(estacion=estacion, fecha__gte=date(2024, 10, 1)).delete()
    ficha = ficha_temporada(estacion, "2024-2025")
    assert ficha["calor"]["dias_sobre_umbral"] is None
    assert ficha["calor"]["calidad_dato"]["confiable"] is False
    assert "motivo_nulo" in ficha["calor"]
    # Rachas y días críticos retienen su alcance anual.
    assert ficha["calor"]["racha_maxima_dias"] == 1
    assert ficha["dias_criticos"][0]["fecha"] == "2024-09-30"


def test_lluvia_y_comparacion_usan_mayo_agosto_y_el_mismo_corte(estacion, monkeypatch):
    for fecha, mm in [(date(2024, 5, 1), 10), (date(2024, 5, 2), 20), (date(2024, 5, 3), 99)]:
        ResumenDiario.objects.create(
            estacion=estacion, fecha=fecha, temporada=temporada_de(fecha), precipitacion=mm
        )
    monkeypatch.setattr("apps.clima.lluvia.timezone.localdate", lambda: date(2024, 5, 2))
    lluvia = lluvia_invernal(estacion, "2024-2025")
    comparacion = comparar_temporadas(estacion, "2024-2025", "2023-2024", hoy=date(2024, 5, 2))
    metrica = next(
        m["temporada"] for m in comparacion["metricas"] if m["metrica"] == "lluvia_invernal"
    )
    assert lluvia["acumulado_mm"] == metrica["valor"] == 30
    assert lluvia["dias_con_dato"] == metrica["dias_con_dato"] == 2
    assert lluvia["dias_esperados"] == metrica["dias_esperados"] == 2
    assert lluvia["completitud_pct"] == metrica["completitud_pct"] == 100
