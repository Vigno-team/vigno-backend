"""E1C-52: cortes numéricos para clasificar cada temporada."""

from datetime import date, timedelta

import pytest

from apps.clima.clasificacion import (
    ETIQUETAS_HIDRICA,
    ETIQUETAS_TERMICA,
    UMBRAL_HIDRICA_PCT,
    UMBRAL_TERMICA_PCT,
    _etiqueta,
    clasificar_temporada,
)
from apps.clima.lluvia import comparar_lluvia_invernal
from apps.clima.models import Estacion, ResumenDiario
from apps.clima.temporadas import temporada_de

pytestmark = pytest.mark.django_db

HOY = date(2026, 10, 6)


@pytest.fixture
def estacion():
    return Estacion.objects.create(nombre="Prueba", codigo="prueba-01", latitud=-35.52)


def cargar(estacion, inicio, cantidad, **datos):
    ResumenDiario.objects.bulk_create(
        ResumenDiario(
            estacion=estacion,
            fecha=inicio + timedelta(days=i),
            temporada=temporada_de(inicio + timedelta(days=i)),
            **datos,
        )
        for i in range(cantidad)
    )


def veranos(estacion, tmedia_por_anio):
    """Un verano completo (1 oct - 30 abr) por año de inicio. Winkler = 212 * (tmedia - 10)."""
    for anio, tmedia in tmedia_por_anio.items():
        cargar(estacion, date(anio, 10, 1), 212, tmedia=tmedia)


def inviernos(estacion, mm_por_dia_por_anio):
    """Un invierno completo (1 may - 31 ago) por año. Acumulado = 123 * mm."""
    for anio, mm in mm_por_dia_por_anio.items():
        cargar(estacion, date(anio, 5, 1), 123, precipitacion=mm)


# Cortes


def test_los_cortes_estan_en_un_solo_lugar_y_son_numericos():
    assert UMBRAL_TERMICA_PCT > 0
    assert UMBRAL_HIDRICA_PCT > 0


@pytest.mark.parametrize(
    ("pct", "esperado"),
    [(5.0, "calida"), (4.9, "normal"), (0.0, "normal"), (-4.9, "normal"), (-5.0, "fria")],
)
def test_el_corte_incluye_el_limite(pct, esperado):
    assert _etiqueta(pct, 5.0, ETIQUETAS_TERMICA) == esperado


@pytest.mark.parametrize(
    ("pct", "esperado"),
    [(20.0, "lluviosa"), (19.9, "normal"), (-19.9, "normal"), (-20.0, "seca")],
)
def test_corte_hidrico(pct, esperado):
    assert _etiqueta(pct, 20.0, ETIQUETAS_HIDRICA) == esperado


# Eje térmico (Winkler contra el promedio de la estación)


@pytest.mark.parametrize(
    ("tmedia", "esperada", "pct"),
    [(22, "calida", 15.4), (18, "fria", -16.7), (20.2, "normal", 1.6)],
)
def test_clasificacion_termica(estacion, tmedia, esperada, pct):
    # Cuatro veranos de Winkler 2120 y el evaluado (2025-2026).
    veranos(estacion, {2021: 20, 2022: 20, 2023: 20, 2024: 20, 2025: tmedia})

    r = clasificar_temporada("prueba-01", "2025-2026", hoy=HOY)

    assert r["termica"] == esperada
    termica = r["detalle"]["termica"]
    assert termica["diferencia_pct"] == pct
    assert termica["temporadas_en_promedio"] == 5
    assert termica["modo"] == "completa"


# Eje hídrico (lluvia invernal contra el promedio de la estación)


@pytest.mark.parametrize(
    ("mm", "esperada", "pct"),
    [(3, "lluviosa", 33.3), (1, "seca", -42.8), (2.2, "normal", 7.3)],
)
def test_clasificacion_hidrica(estacion, mm, esperada, pct):
    inviernos(estacion, {2022: 2, 2023: 2, 2024: 2, 2025: mm})

    r = clasificar_temporada("prueba-01", "2025-2026", hoy=HOY)  # invierno de 2025

    assert r["hidrica"] == esperada
    assert r["detalle"]["hidrica"]["diferencia_pct"] == pct


def test_la_clasificacion_hidrica_coincide_con_la_diferencia_de_lluvia_invernal(estacion):
    inviernos(estacion, {2021: 2, 2022: 3, 2023: 1, 2024: 4})

    detalle = clasificar_temporada("prueba-01", "2024-2025", hoy=HOY)["detalle"]["hidrica"]

    historico = comparar_lluvia_invernal("prueba-01", temporadas=["2024-2025"])
    assert detalle["promedio_historico"] == historico["promedio_historico_mm"]
    assert detalle["diferencia_pct"] == historico["temporadas"][0]["diferencia_pct"]


# Temporada en curso: acumulado al mismo día calendario


def test_temporada_en_curso_usa_el_acumulado_al_mismo_dia(estacion):
    # Cinco veranos completos de Winkler 2120 y la temporada 2026-2027 con 6 días tmedia 22.
    veranos(estacion, {2021: 20, 2022: 20, 2023: 20, 2024: 20, 2025: 20})
    cargar(estacion, date(2026, 10, 1), 6, tmedia=22)

    termica = clasificar_temporada("prueba-01", "2026-2027", hoy=HOY)["detalle"]["termica"]

    assert termica["modo"] == "al_mismo_dia"
    assert termica["valor"] == 72  # 6 días * 12
    assert termica["promedio_historico"] == 60  # 6 días * 10, no 2120
    assert termica["temporadas_en_promedio"] == 5  # la temporada en curso no entra
    assert termica["etiqueta"] == "calida"  # +20 %


def test_una_temporada_en_curso_no_se_clasifica_contra_el_total_de_las_demas(estacion):
    # Si se comparara 72 contra 2120 saldría "fría" (-97 %): el error que evita el corte.
    veranos(estacion, {2021: 20, 2022: 20, 2023: 20, 2024: 20, 2025: 20})
    cargar(estacion, date(2026, 10, 1), 6, tmedia=20)
    assert clasificar_temporada("prueba-01", "2026-2027", hoy=HOY)["termica"] == "normal"


# Datos insuficientes


def test_con_una_sola_temporada_no_hay_promedio_y_no_se_clasifica(estacion):
    veranos(estacion, {2025: 22})

    r = clasificar_temporada("prueba-01", "2025-2026", hoy=HOY)

    assert r["termica"] is None
    assert r["detalle"]["termica"]["temporadas_en_promedio"] == 1
    assert "al menos 2" in r["detalle"]["termica"]["observacion"]


def test_temporada_sin_datos_suficientes_no_se_clasifica(estacion):
    veranos(estacion, {2021: 20, 2022: 20, 2023: 20})
    cargar(estacion, date(2025, 10, 1), 10, tmedia=30)  # 4,7 % de la temporada: no confiable

    r = clasificar_temporada("prueba-01", "2025-2026", hoy=HOY)

    assert r["termica"] is None
    assert r["hidrica"] is None
    assert "datos suficientes" in r["detalle"]["termica"]["observacion"]


def test_las_temporadas_no_confiables_no_entran_en_el_promedio(estacion):
    veranos(estacion, {2021: 20, 2022: 20, 2023: 20, 2025: 20})
    cargar(estacion, date(2024, 10, 1), 10, tmedia=40)  # incompleta: se ignora

    termica = clasificar_temporada("prueba-01", "2025-2026", hoy=HOY)["detalle"]["termica"]

    assert termica["temporadas_en_promedio"] == 4
    assert termica["promedio_historico"] == 2120
    assert termica["etiqueta"] == "normal"


def test_promedio_cero_no_divide(estacion):
    veranos(estacion, {2021: 5, 2022: 5, 2023: 5})  # Winkler 0 todos los años

    termica = clasificar_temporada("prueba-01", "2023-2024", hoy=HOY)["detalle"]["termica"]

    assert termica["promedio_historico"] == 0
    assert termica["etiqueta"] is None
    assert termica["diferencia_pct"] is None
    assert "0" in termica["observacion"]


def test_ejes_independientes(estacion):
    veranos(estacion, {2021: 20, 2022: 20, 2023: 20, 2025: 22})
    r = clasificar_temporada("prueba-01", "2025-2026", hoy=HOY)
    assert r["termica"] == "calida"
    assert r["hidrica"] is None  # sin datos de lluvia no se inventa


# Criterio explícito


def test_el_criterio_publica_los_numeros(estacion):
    veranos(estacion, {2021: 20, 2022: 20})
    criterio = clasificar_temporada("prueba-01", "2022-2023", hoy=HOY)["criterio"]
    assert "5 %" in criterio and "20 %" in criterio
    assert "Winkler" in criterio and "mayo-agosto" in criterio


def test_estacion_inexistente_falla():
    with pytest.raises(Estacion.DoesNotExist):
        clasificar_temporada("no-existe", "2025-2026", hoy=HOY)


def test_temporada_en_curso_queda_marcada_como_parcial(estacion):
    veranos(estacion, {2023: 18, 2024: 18, 2025: 18})
    cargar(estacion, date(2026, 10, 1), 6, tmedia=20)

    c = clasificar_temporada("prueba-01", "2026-2027", hoy=HOY)

    assert c["en_curso"] is True
    assert c["parcial_hasta"] == HOY.isoformat()
    assert "Temporada en curso" in c["criterio"]


def test_temporada_terminada_no_queda_marcada_como_parcial(estacion):
    veranos(estacion, {2022: 18, 2023: 18, 2024: 19})
    c = clasificar_temporada("prueba-01", "2024-2025", hoy=HOY)
    assert c["en_curso"] is False and c["parcial_hasta"] is None
    assert "Temporada en curso" not in c["criterio"]
