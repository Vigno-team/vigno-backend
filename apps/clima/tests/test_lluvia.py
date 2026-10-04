from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from apps.clima.lluvia import comparar_lluvia_invernal, eventos_lluvia, lluvia_invernal
from apps.clima.models import Estacion, MedicionHoraria, ResumenDiario
from apps.clima.temporadas import rango_invernal, temporada_de

pytestmark = pytest.mark.django_db

SANTIAGO = ZoneInfo("America/Santiago")


@pytest.fixture
def estacion():
    return Estacion.objects.create(nombre="Lluvia", codigo="lluvia-01")


def cargar_dias(estacion, desde, hasta, mm):
    """Un ResumenDiario por día entre `desde` y `hasta` (inclusive), todos con `mm`."""
    dias = (hasta - desde).days + 1
    ResumenDiario.objects.bulk_create(
        ResumenDiario(
            estacion=estacion,
            fecha=desde + timedelta(days=i),
            temporada=temporada_de(desde + timedelta(days=i)),
            precipitacion=mm,
        )
        for i in range(dias)
    )


def cargar_invierno(estacion, anio, mm_por_dia):
    ini, fin = rango_invernal(f"{anio}-{anio + 1}")
    cargar_dias(estacion, ini, fin, mm_por_dia)


def cargar_horas(estacion, *horas):
    """horas = (año, mes, día, hora, mm) en hora de Chile."""
    MedicionHoraria.objects.bulk_create(
        MedicionHoraria(
            estacion=estacion,
            timestamp=datetime(a, m, d, h, tzinfo=SANTIAGO),
            variable="precipitacion",
            frecuencia="H",
            valor=mm,
        )
        for a, m, d, h, mm in horas
    )


# período invernal


def test_rango_invernal():
    assert rango_invernal("2024-2025") == (date(2024, 5, 1), date(2024, 8, 31))


# acumulado invernal


def test_acumulado_solo_cuenta_el_periodo_invernal(estacion):
    cargar_dias(estacion, date(2024, 4, 30), date(2024, 9, 1), 1.0)  # un día de más a cada lado

    res = lluvia_invernal("lluvia-01", "2024-2025")

    assert res["periodo"] == {"desde": "2024-05-01", "hasta": "2024-08-31"}
    assert res["acumulado_mm"] == 123.0  # mayo a agosto = 123 días
    assert res["dias_con_dato"] == 123
    assert res["confiable"] is True
    assert "observacion" not in res


def test_el_invierno_se_busca_por_fecha_y_no_por_la_columna_temporada(estacion):
    # mayo-junio de 2024 quedan guardados con temporada "2023-2024", julio-agosto con "2024-2025"
    cargar_invierno(estacion, 2024, 1.0)
    assert set(ResumenDiario.objects.values_list("temporada", flat=True)) == {
        "2023-2024",
        "2024-2025",
    }

    assert lluvia_invernal("lluvia-01", "2024-2025")["acumulado_mm"] == 123.0
    assert lluvia_invernal("lluvia-01", "2023-2024")["acumulado_mm"] is None


def test_acumulado_incompleto_no_es_confiable(estacion):
    cargar_dias(estacion, date(2024, 5, 1), date(2024, 5, 10), 2.0)  # 10 de 123 días

    res = lluvia_invernal("lluvia-01", "2024-2025")

    assert res["acumulado_mm"] == 20.0
    assert res["completitud_pct"] == 8.1
    assert res["confiable"] is False
    assert "parcial" in res["observacion"]


def test_acumulado_sin_datos(estacion):
    res = lluvia_invernal("lluvia-01", "2024-2025")

    assert res["acumulado_mm"] is None
    assert res["confiable"] is False
    assert "sin datos" in res["observacion"]


def test_acumulado_estacion_inexistente_falla():
    with pytest.raises(Estacion.DoesNotExist):
        lluvia_invernal("no-existe", "2024-2025")


# eventos de lluvia


def test_evento_que_cruza_medianoche_entrega_intensidad_duracion_y_total_diario(estacion):
    cargar_horas(
        estacion,
        (2024, 6, 10, 22, 1.0),
        (2024, 6, 10, 23, 4.0),
        (2024, 6, 11, 0, 2.0),  # mismo evento, ya es el día 11
        (2024, 6, 11, 14, 0.5),  # 14 horas después: evento nuevo
        (2024, 6, 11, 15, 0.5),
    )

    res = eventos_lluvia("lluvia-01", "2024-06-10", "2024-06-11")

    assert len(res["eventos"]) == 2
    primero = res["eventos"][0]
    assert primero["intensidad_max_mm_h"] == 4.0
    assert primero["duracion_horas"] == 3.0
    assert primero["horas_con_lluvia"] == 3
    assert primero["total_mm"] == 7.0
    assert primero["dias"] == [
        {"fecha": "2024-06-10", "total_dia_mm": 5.0},
        {"fecha": "2024-06-11", "total_dia_mm": 3.0},  # el día completo, no solo el evento
    ]
    assert res["eventos"][1]["total_mm"] == 1.0


def test_pocas_horas_secas_no_parten_el_evento(estacion):
    cargar_horas(estacion, (2024, 6, 10, 10, 1.0), (2024, 6, 10, 15, 3.0))  # 4 horas secas

    res = eventos_lluvia("lluvia-01", "2024-06-10", "2024-06-10")

    assert len(res["eventos"]) == 1
    assert res["eventos"][0]["duracion_horas"] == 6.0
    assert res["eventos"][0]["horas_con_lluvia"] == 2


def test_limite_de_la_separacion_entre_eventos(estacion):
    # 6 horas secas seguidas separan eventos; con 5 sigue siendo el mismo
    cargar_horas(estacion, (2024, 6, 10, 10, 1.0), (2024, 6, 10, 16, 1.0))  # 5 horas secas
    cargar_horas(estacion, (2024, 6, 11, 10, 1.0), (2024, 6, 11, 17, 1.0))  # 6 horas secas

    res = eventos_lluvia("lluvia-01", "2024-06-10", "2024-06-11")

    assert [e["horas_con_lluvia"] for e in res["eventos"]] == [2, 1, 1]


def test_la_separacion_de_eventos_se_puede_cambiar(estacion):
    cargar_horas(estacion, (2024, 6, 10, 10, 1.0), (2024, 6, 10, 15, 3.0))

    res = eventos_lluvia("lluvia-01", "2024-06-10", "2024-06-10", separacion_horas=2)

    assert len(res["eventos"]) == 2


def test_eventos_respeta_el_rango_y_solo_usa_datos_horarios(estacion):
    cargar_horas(estacion, (2024, 6, 9, 12, 5.0), (2024, 6, 10, 12, 2.0))
    MedicionHoraria.objects.create(  # un dato diario no es un evento horario
        estacion=estacion,
        timestamp=datetime(2024, 6, 10, 12, tzinfo=SANTIAGO),
        variable="precipitacion",
        frecuencia="D",
        valor=99.0,
    )

    res = eventos_lluvia("lluvia-01", "2024-06-10", "2024-06-10")

    assert [e["total_mm"] for e in res["eventos"]] == [2.0]


def test_eventos_sin_datos_horarios(estacion):
    res = eventos_lluvia("lluvia-01", "2024-06-10", "2024-06-11")

    assert res["eventos"] == []
    assert "sin datos horarios" in res["observacion"]


def test_eventos_ignora_horas_sin_lluvia(estacion):
    cargar_horas(estacion, (2024, 6, 10, 10, 0.0), (2024, 6, 10, 11, 0.0))

    res = eventos_lluvia("lluvia-01", "2024-06-10", "2024-06-10")

    assert res["eventos"] == []
    assert res["observacion"] == "sin lluvia en el rango"


# comparación contra el promedio histórico


def test_comparacion_contra_el_promedio_historico(estacion):
    cargar_invierno(estacion, 2022, 1.0)  # 123 mm
    cargar_invierno(estacion, 2023, 2.0)  # 246 mm
    cargar_invierno(estacion, 2024, 3.0)  # 369 mm

    res = comparar_lluvia_invernal("lluvia-01")

    assert res["promedio_historico_mm"] == 246.0
    assert res["temporadas_en_promedio"] == 3
    assert [t["temporada"] for t in res["temporadas"]] == ["2022-2023", "2023-2024", "2024-2025"]
    assert [t["diferencia_mm"] for t in res["temporadas"]] == [-123.0, 0.0, 123.0]
    assert [t["diferencia_pct"] for t in res["temporadas"]] == [-50.0, 0.0, 50.0]


def test_comparacion_de_algunas_temporadas_usa_el_promedio_de_todas(estacion):
    cargar_invierno(estacion, 2022, 1.0)
    cargar_invierno(estacion, 2023, 2.0)
    cargar_invierno(estacion, 2024, 3.0)

    res = comparar_lluvia_invernal("lluvia-01", temporadas=["2024-2025"])

    assert res["promedio_historico_mm"] == 246.0
    assert [t["temporada"] for t in res["temporadas"]] == ["2024-2025"]


def test_invierno_no_confiable_no_entra_al_promedio(estacion):
    cargar_invierno(estacion, 2022, 1.0)
    cargar_invierno(estacion, 2023, 3.0)
    cargar_dias(estacion, date(2024, 5, 1), date(2024, 5, 5), 50.0)  # incompleto: 250 mm

    res = comparar_lluvia_invernal("lluvia-01")

    assert res["promedio_historico_mm"] == 246.0  # (123 + 369) / 2, sin el invierno de 2024
    assert res["temporadas_en_promedio"] == 2
    parcial = res["temporadas"][-1]
    assert parcial["temporada"] == "2024-2025"
    assert parcial["confiable"] is False


def test_comparacion_sin_suficientes_inviernos_confiables(estacion):
    cargar_invierno(estacion, 2023, 2.0)

    res = comparar_lluvia_invernal("lluvia-01")

    assert res["promedio_historico_mm"] is None
    assert "al menos 2" in res["observacion"]
    assert res["temporadas"][0]["diferencia_mm"] is None
