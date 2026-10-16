from datetime import date, timedelta

import pytest
from django.test import override_settings

from apps.clima import temporadas
from apps.clima.lluvia_fuera_invierno import lluvia_fuera_invierno
from apps.clima.models import Estacion, ResumenDiario
from apps.clima.temporadas import temporada_de

pytestmark = pytest.mark.django_db


@pytest.fixture
def estacion():
    return Estacion.objects.create(nombre="Métrica lluvia", codigo="metrica-lluvia")


def cargar_anio_agricola(estacion, anio, lluvia=None, nulos=()):
    lluvia = lluvia or {}
    nulos = set(nulos)
    inicio = date(anio, 5, 1)
    fin = date(anio + 1, 5, 1)
    ResumenDiario.objects.bulk_create(
        ResumenDiario(
            estacion=estacion,
            fecha=fecha,
            temporada=temporada_de(fecha),
            precipitacion=None if fecha in nulos else lluvia.get(fecha, 0.0),
        )
        for fecha in (inicio + timedelta(days=i) for i in range((fin - inicio).days))
    )


def test_metricas_calculan_ventanas_y_etapas(estacion):
    cargar_anio_agricola(
        estacion,
        2024,
        {
            date(2024, 5, 1): 8,
            date(2024, 9, 1): 12,
            date(2024, 10, 1): 10,
            date(2024, 11, 30): 5,
            date(2025, 1, 31): 10,
            date(2025, 2, 1): 10,
            date(2025, 4, 30): 2,
        },
    )

    resultado = lluvia_fuera_invierno(estacion, "2024-2025", hoy=date(2025, 5, 1))

    assert resultado["total_anio_agricola_mm"] == 57
    assert resultado["septiembre_mm"] == 12
    assert resultado["crecimiento_mm"] == 37
    assert [etapa["mm"] for etapa in resultado["etapas"]] == [15, 10, 12]
    assert resultado["dias_lluvia_intensa"] == [
        {"fecha": "2024-10-01", "mm": 10, "etapa": "brotacion_floracion"},
        {"fecha": "2025-01-31", "mm": 10, "etapa": "cuaja_envero"},
        {"fecha": "2025-02-01", "mm": 10, "etapa": "maduracion_cosecha"},
    ]
    assert resultado["calidad_dato"]["completitud_pct"] == 100
    assert resultado["calidad_dato"]["confiable"] is True
    assert all(item["confiable"] for item in resultado["calidad_dato"]["ventanas"].values())


@pytest.mark.parametrize(("faltantes", "confiable"), [(12, True), (13, False)])
def test_completitud_de_ventana_usa_umbral_80(estacion, faltantes, confiable):
    dias_nulos = [date(2024, 10, 1) + timedelta(days=i) for i in range(faltantes)]
    cargar_anio_agricola(estacion, 2024, nulos=dias_nulos)

    resultado = lluvia_fuera_invierno(estacion, "2024-2025", hoy=date(2025, 5, 1))

    calidad = resultado["calidad_dato"]["ventanas"]["etapa_brotacion_floracion"]
    assert calidad["confiable"] is confiable
    assert calidad["completitud_pct"] == round((61 - faltantes) / 61 * 100, 1)


def test_promedios_usan_dos_temporadas_completas_e_incluyen_la_evaluada(estacion):
    cargar_anio_agricola(estacion, 2021)
    cargar_anio_agricola(estacion, 2022)
    cargar_anio_agricola(estacion, 2023, {date(2023, 10, 1): 20})
    cargar_anio_agricola(estacion, 2024, {date(2024, 10, 1): 40})

    resultado = lluvia_fuera_invierno(estacion, "2024-2025", hoy=date(2025, 5, 1))

    assert resultado["etapas"][0]["promedio_mm"] == 15
    assert resultado["etapas"][0]["diferencia_pct"] == 166.7
    assert resultado["etapas"][0]["temporadas_en_promedio"] == 4
    assert resultado["meses_inusuales"] == [
        {
            "mes": "2024-10",
            "mm": 40,
            "promedio_mm": 15,
            "temporadas_en_promedio": 4,
        }
    ]


def test_promedio_no_se_publica_con_una_sola_temporada_confiable(estacion):
    cargar_anio_agricola(estacion, 2024, {date(2024, 10, 1): 20})
    cargar_anio_agricola(estacion, 2026, {date(2026, 10, 1): 40})

    resultado = lluvia_fuera_invierno(estacion, "2026-2027", hoy=date(2026, 10, 16))

    assert resultado["etapas"][0]["promedio_mm"] is None
    assert resultado["etapas"][0]["temporadas_en_promedio"] == 1
    assert resultado["meses_inusuales"] == []


def test_etapa_en_curso_compara_contra_el_mismo_dia_historico(estacion):
    for anio in (2023, 2024):
        lluvia_historica = {
            **{date(anio, 10, 1) + timedelta(days=i): 1 for i in range(16)},
            date(anio, 10, 20): 45,
        }
        cargar_anio_agricola(estacion, anio, lluvia_historica)
    cargar_anio_agricola(
        estacion,
        2026,
        {date(2026, 10, 1) + timedelta(days=i): 1 for i in range(16)},
    )

    resultado = lluvia_fuera_invierno(estacion, "2026-2027", hoy=date(2026, 10, 16))

    etapa = resultado["etapas"][0]
    assert etapa["mm"] == 16
    assert etapa["promedio_mm"] == 16
    assert etapa["temporadas_en_promedio"] == 2
    assert etapa["en_curso"] is True
    assert etapa["evaluado_hasta"] == "2026-10-16"
    assert etapa["diferencia_pct"] == 0


def test_etapa_no_confiable_no_publica_diferencia(estacion):
    cargar_anio_agricola(estacion, 2022, {date(2022, 10, 1): 10})
    cargar_anio_agricola(estacion, 2023, {date(2023, 10, 1): 10})
    faltantes = [date(2024, 10, 1) + timedelta(days=i) for i in range(13)]
    cargar_anio_agricola(estacion, 2024, {date(2024, 10, 1): 20}, nulos=faltantes)

    resultado = lluvia_fuera_invierno(estacion, "2024-2025", hoy=date(2025, 5, 1))

    etapa = resultado["etapas"][0]
    assert resultado["calidad_dato"]["ventanas"]["etapa_brotacion_floracion"]["confiable"] is False
    assert etapa["diferencia_pct"] is None


def test_calidad_global_ignora_etapas_futuras(estacion):
    cargar_anio_agricola(estacion, 2026)

    resultado = lluvia_fuera_invierno(estacion, "2026-2027", hoy=date(2026, 10, 16))

    calidad = resultado["calidad_dato"]
    assert calidad["completitud_pct"] == 100
    assert calidad["confiable"] is True
    assert calidad["en_curso"] is True
    assert calidad["evaluado_hasta"] == "2026-10-16"
    assert calidad["ventanas"]["etapa_cuaja_envero"]["completitud_pct"] is None


def test_temporada_sin_lluvia_devuelve_motivo_nulo(estacion):
    resultado = lluvia_fuera_invierno(estacion, "2024-2025", hoy=date(2025, 5, 1))

    assert resultado["total_anio_agricola_mm"] is None
    assert resultado["motivo_nulo"] == "Sin datos de precipitación en el año agrícola."


def test_dia_lluvioso_en_hueco_entre_etapas_no_aborta_ficha(estacion, monkeypatch):
    monkeypatch.setattr(
        temporadas,
        "ETAPAS_CRECIMIENTO",
        (
            ("brotacion_floracion", (10, 1), (11, 30)),
            ("cuaja_envero", (12, 2), (1, 31)),
            ("maduracion_cosecha", (2, 1), (4, 30)),
        ),
    )
    cargar_anio_agricola(estacion, 2024, {date(2024, 12, 1): 25})

    resultado = lluvia_fuera_invierno(estacion, "2024-2025", hoy=date(2025, 5, 1))

    assert resultado["dias_lluvia_intensa"] == []


@override_settings(UMBRAL_LLUVIA_INTENSA_MM=15, FACTOR_MES_INUSUAL=3)
def test_umbrales_son_configurables(estacion):
    cargar_anio_agricola(estacion, 2021)
    cargar_anio_agricola(estacion, 2022)
    cargar_anio_agricola(estacion, 2023, {date(2023, 10, 1): 20})
    cargar_anio_agricola(estacion, 2024, {date(2024, 10, 1): 40})

    resultado = lluvia_fuera_invierno(estacion, "2024-2025", hoy=date(2025, 5, 1))

    assert len(resultado["dias_lluvia_intensa"]) == 1
    assert resultado["meses_inusuales"] == []


@pytest.mark.parametrize(
    ("anio", "lluvia", "historico", "crecimiento", "dias_intensos", "meses_inusuales"),
    [
        (
            2021,
            {
                date(2022, 4, 21): 30,
                date(2022, 4, 22): 30,
                date(2022, 4, 25): 30,
                date(2022, 4, 26): 30,
            },
            {date(2021, 4, 1): 43},
            120,
            4,
            ["2022-04"],
        ),
        (
            2023,
            {
                date(2023, 10, 1): 13,
                date(2023, 10, 2): 13,
                date(2023, 10, 3): 12,
                date(2023, 10, 4): 12,
                date(2023, 11, 1): 17,
                date(2023, 11, 2): 17,
                date(2023, 11, 3): 16,
            },
            {date(2022, 10, 1): 20, date(2022, 11, 1): 20},
            100,
            7,
            ["2023-10", "2023-11"],
        ),
        (2025, {date(2026, 3, 1): 61}, {date(2025, 3, 1): 16}, 61, 1, ["2026-03"]),
        (2024, {date(2024, 10, 1): 4, date(2025, 4, 1): 6}, {}, 10, 0, []),
    ],
    ids=("cosecha-abril", "floracion-oct-nov", "maduracion-marzo", "temporada-seca"),
)
def test_regresion_con_los_cuatro_casos_cliente(
    estacion, anio, lluvia, historico, crecimiento, dias_intensos, meses_inusuales
):
    for anio_historico in range(anio - 4, anio):
        lluvia_historica = historico if anio_historico == anio - 1 else None
        cargar_anio_agricola(estacion, anio_historico, lluvia_historica)
    cargar_anio_agricola(estacion, anio, lluvia)

    resultado = lluvia_fuera_invierno(estacion, f"{anio}-{anio + 1}", hoy=date(anio + 2, 5, 1))

    assert resultado["crecimiento_mm"] == crecimiento
    assert len(resultado["dias_lluvia_intensa"]) == dias_intensos
    assert [mes["mes"] for mes in resultado["meses_inusuales"]] == meses_inusuales
