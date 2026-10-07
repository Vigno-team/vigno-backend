"""D3.1: comparación entre temporadas (E1C-50) y entre estaciones (E1C-51)."""

from datetime import date, timedelta

import pytest

from apps.clima.comparacion import (
    _trasladar,
    comparar_con_anteriores,
    comparar_estaciones,
    comparar_temporadas,
    cortes,
    valor_metrica,
)
from apps.clima.indices import calcular_indice_huglin, calcular_indice_winkler
from apps.clima.models import ConfiguracionCalidad, Estacion, IndiceClimatico, ResumenDiario
from apps.clima.temporadas import temporada_de

pytestmark = pytest.mark.django_db

HOY = date(2026, 10, 6)  # fijo: la temporada 2026-2027 está recién empezada


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


def metrica(resultado, nombre):
    return next(m for m in resultado["metricas"] if m["metrica"] == nombre)


# E1C-50: dos temporadas


def test_diferencial_de_cada_indice_y_metrica(estacion):
    # Verano 2023-2024: 212 días, tmedia 20 -> Winkler 2120. Verano 2022-2023: tmedia 15 -> 1060.
    cargar(estacion, date(2023, 10, 1), 212, tmedia=20, tmax=36, tmin=8)
    cargar(estacion, date(2022, 10, 1), 212, tmedia=15, tmax=30, tmin=5)
    cargar(estacion, date(2023, 5, 1), 123, precipitacion=3)  # invierno 2023: 369 mm
    cargar(estacion, date(2022, 5, 1), 123, precipitacion=2)  # invierno 2022: 246 mm

    r = comparar_temporadas("prueba-01", "2023-2024", "2022-2023", hoy=HOY)

    assert [m["metrica"] for m in r["metricas"]] == [
        "winkler",
        "huglin",
        "dias_sobre_umbral",
        "lluvia_invernal",
    ]
    w = metrica(r, "winkler")
    assert (w["temporada"]["valor"], w["referencia"]["valor"]) == (2120, 1060)
    assert (w["diferencia"], w["diferencia_pct"], w["comparable"]) == (1060, 100, True)
    assert w["modo"] == "completa"
    # Huglin (1 oct - 31 mar): 18 por día en 2023-2024 (183 días, año bisiesto) = 3294
    # y 12,5 por día en 2022-2023 (182 días) = 2275
    h = metrica(r, "huglin")
    assert (h["temporada"]["valor"], h["referencia"]["valor"]) == (3294, 2275)
    # Días >= 35 °C: 212 contra 0 (la referencia no tiene tmax >= 35)
    d = metrica(r, "dias_sobre_umbral")
    assert (d["temporada"]["valor"], d["referencia"]["valor"], d["diferencia"]) == (212, 0, 212)
    assert d["diferencia_pct"] is None  # no se divide por 0
    ll = metrica(r, "lluvia_invernal")
    assert (ll["temporada"]["valor"], ll["referencia"]["valor"]) == (369, 246)
    assert (ll["diferencia"], ll["diferencia_pct"]) == (123, 50)


def test_coincide_con_los_indices_que_guarda_el_pipeline(estacion):
    cargar(estacion, date(2023, 10, 1), 212, tmedia=18, tmax=29, tmin=7)
    calcular_indice_winkler(estacion, "2023-2024")
    calcular_indice_huglin(estacion, "2023-2024")
    umbral = ConfiguracionCalidad.obtener_umbral()
    fin = date(2024, 4, 30)

    for nombre, indice in (("winkler", "Winkler"), ("huglin", "Huglin")):
        guardado = IndiceClimatico.objects.get(estacion=estacion, indice=indice)
        calculado = valor_metrica(estacion, nombre, "2023-2024", fin, umbral)
        assert calculado["valor"] == guardado.valor
        assert calculado["dias_con_dato"] == guardado.dias_con_dato
        assert calculado["dias_esperados"] == guardado.dias_esperados


def test_temporada_en_curso_se_compara_al_mismo_dia_calendario(estacion):
    # Hoy es 6 de octubre de 2026: la temporada 2026-2027 lleva 6 días con tmedia 22.
    cargar(estacion, date(2026, 10, 1), 6, tmedia=22, tmax=30, tmin=10)
    # Año anterior completo con tmedia 12: 2 °C·día por día (424 en toda la temporada).
    cargar(estacion, date(2025, 10, 1), 212, tmedia=12, tmax=20, tmin=4)

    r = comparar_temporadas("prueba-01", "2026-2027", "2025-2026", hoy=HOY)

    w = metrica(r, "winkler")
    assert w["modo"] == "al_mismo_dia"
    assert w["temporada"]["valor"] == 72  # 6 días * 12
    assert w["referencia"]["valor"] == 12  # solo del 1 al 6 de octubre de 2025: 6 días * 2
    assert w["referencia"]["hasta"] == "2025-10-06"
    assert w["temporada"]["dias_esperados"] == w["referencia"]["dias_esperados"] == 6
    assert w["diferencia"] == 60
    assert w["comparable"] is True


def test_dos_temporadas_terminadas_no_se_cortan(estacion):
    cargar(estacion, date(2024, 10, 1), 212, tmedia=20)
    cargar(estacion, date(2023, 10, 1), 212, tmedia=20)
    _, modo = cortes("winkler", ["2024-2025", "2023-2024"], HOY)
    assert modo == "completa"


def test_el_corte_del_29_de_febrero_pasa_al_28():
    assert _trasladar(date(2028, 2, 29), date(2027, 10, 1), date(2025, 10, 1)) == date(2026, 2, 28)
    assert _trasladar(date(2028, 2, 29), date(2027, 10, 1), date(2027, 10, 1)) == date(2028, 2, 29)


def test_dato_insuficiente_no_se_compara(estacion):
    cargar(estacion, date(2023, 10, 1), 212, tmedia=20, tmax=30, tmin=10)
    cargar(estacion, date(2022, 10, 1), 10, tmedia=15, tmax=25, tmin=5)  # 4,7 % de la temporada

    w = metrica(comparar_temporadas("prueba-01", "2023-2024", "2022-2023", hoy=HOY), "winkler")

    assert w["referencia"]["valor"] is not None  # el valor parcial se informa...
    assert w["referencia"]["confiable"] is False  # ...pero no se usa para comparar
    assert w["comparable"] is False
    assert w["diferencia"] is None and w["diferencia_pct"] is None
    assert "2022-2023" in w["observacion"]


def test_sin_datos_en_una_temporada_devuelve_nulos(estacion):
    cargar(estacion, date(2023, 10, 1), 212, tmedia=20)
    r = comparar_temporadas("prueba-01", "2023-2024", "2001-2002", hoy=HOY)
    ll = metrica(r, "lluvia_invernal")
    assert ll["referencia"]["valor"] is None
    assert ll["referencia"]["completitud_pct"] == 0
    assert ll["comparable"] is False


def test_un_cero_observado_es_dato_y_su_ausencia_no(estacion):
    cargar(estacion, date(2023, 5, 1), 123, precipitacion=0)
    cargar(estacion, date(2022, 5, 1), 123, precipitacion=None)
    ll = metrica(
        comparar_temporadas("prueba-01", "2023-2024", "2022-2023", hoy=HOY), "lluvia_invernal"
    )
    assert ll["temporada"]["valor"] == 0 and ll["temporada"]["confiable"] is True
    assert ll["referencia"]["valor"] is None and ll["referencia"]["confiable"] is False


def test_huglin_sin_latitud_no_es_comparable():
    est = Estacion.objects.create(nombre="Sin latitud", codigo="sin-lat", latitud=None)
    cargar(est, date(2023, 10, 1), 212, tmedia=20, tmax=30)
    cargar(est, date(2022, 10, 1), 212, tmedia=20, tmax=30)
    h = metrica(comparar_temporadas("sin-lat", "2023-2024", "2022-2023", hoy=HOY), "huglin")
    assert h["comparable"] is False


def test_estacion_inexistente_falla():
    with pytest.raises(Estacion.DoesNotExist):
        comparar_temporadas("no-existe", "2023-2024", "2022-2023", hoy=HOY)


def test_umbral_de_calidad_se_toma_de_la_configuracion(estacion):
    ConfiguracionCalidad.objects.create(umbral_pct=3)
    cargar(estacion, date(2023, 10, 1), 212, tmedia=20)
    cargar(estacion, date(2022, 10, 1), 10, tmedia=15)  # 4,7 % >= 3 %
    w = metrica(comparar_temporadas("prueba-01", "2023-2024", "2022-2023", hoy=HOY), "winkler")
    assert w["comparable"] is True


def test_comparar_con_cada_temporada_anterior(estacion):
    cargar(estacion, date(2024, 10, 1), 212, tmedia=20)
    cargar(estacion, date(2023, 10, 1), 212, tmedia=18)
    cargar(estacion, date(2022, 10, 1), 212, tmedia=16)

    r = comparar_con_anteriores("prueba-01", "2024-2025", hoy=HOY)

    refs = [c["referencia"] for c in r["comparaciones"]]
    assert refs == ["2022-2023", "2023-2024"]  # solo las que tienen datos, de más antigua a nueva
    assert [metrica(c, "winkler")["diferencia"] for c in r["comparaciones"]] == [
        212 * 4,
        212 * 2,
    ]


# E1C-51: dos estaciones


@pytest.fixture
def otra():
    return Estacion.objects.create(nombre="Otra", codigo="otra-01", latitud=-35.5)


def test_diferencia_sistematica_entre_estaciones(estacion, otra):
    cargar(estacion, date(2024, 1, 1), 10, tmedia=21.5, tmax=31.5, tmin=11.5)
    cargar(otra, date(2024, 1, 1), 10, tmedia=20, tmax=30, tmin=10)

    r = comparar_estaciones("prueba-01", "otra-01")

    assert r["periodo"] == {"desde": "2024-01-01", "hasta": "2024-01-10"}
    for var in ("tmedia", "tmax", "tmin"):
        v = r["variables"][var]
        assert v["dias_comunes"] == 10
        assert v["diferencia_media_c"] == 1.5
        assert v["desviacion_c"] == 0
        assert v["dias_a_mas_calida_pct"] == 100
        assert v["completitud_pct"] == 100 and v["confiable"] is True


def test_solo_cuentan_los_dias_en_que_ambas_tienen_dato(estacion, otra):
    # A tiene 10 días; B solo los últimos 5. El período común es el solapamiento.
    cargar(estacion, date(2024, 1, 1), 10, tmedia=20)
    cargar(otra, date(2024, 1, 6), 5, tmedia=18)

    r = comparar_estaciones("prueba-01", "otra-01")

    assert r["periodo"] == {"desde": "2024-01-06", "hasta": "2024-01-10"}
    assert r["variables"]["tmedia"]["dias_comunes"] == 5
    assert r["variables"]["tmedia"]["diferencia_media_c"] == 2


@pytest.mark.parametrize("sin_dato", ["prueba-01", "otra-01"])
def test_un_dia_sin_dato_en_una_de_ellas_no_sesga_la_diferencia(estacion, otra, sin_dato):
    cargar(estacion, date(2024, 1, 1), 4, tmedia=20)
    cargar(otra, date(2024, 1, 1), 4, tmedia=19)
    ResumenDiario.objects.filter(estacion__codigo=sin_dato, fecha=date(2024, 1, 2)).update(
        tmedia=None
    )

    v = comparar_estaciones("prueba-01", "otra-01")["variables"]["tmedia"]

    assert v["dias_comunes"] == 3
    assert v["completitud_pct"] == 75
    assert v["diferencia_media_c"] == 1


def test_periodo_explicito_y_baja_completitud(estacion, otra):
    cargar(estacion, date(2024, 1, 1), 30, tmedia=20)
    cargar(otra, date(2024, 1, 1), 30, tmedia=19)

    r = comparar_estaciones("prueba-01", "otra-01", date(2024, 1, 1), date(2024, 3, 31))

    v = r["variables"]["tmedia"]
    assert r["dias_en_periodo"] == 91
    assert v["completitud_pct"] == 33
    assert v["confiable"] is False  # 33 % < 80 %


def test_diferencia_cambia_de_signo_y_mide_dispersion(estacion, otra):
    cargar(estacion, date(2024, 1, 1), 2, tmedia=20)
    cargar(otra, date(2024, 1, 1), 2, tmedia=18)
    ResumenDiario.objects.filter(estacion=otra, fecha=date(2024, 1, 2)).update(tmedia=22)

    v = comparar_estaciones("prueba-01", "otra-01")["variables"]["tmedia"]

    assert v["diferencia_media_c"] == 0  # +2 y -2
    assert v["desviacion_c"] == 2.83
    assert v["dias_a_mas_calida_pct"] == 50


def test_estaciones_sin_periodo_comun(estacion, otra):
    cargar(estacion, date(2023, 1, 1), 5, tmedia=20)
    cargar(otra, date(2024, 1, 1), 5, tmedia=20)
    r = comparar_estaciones("prueba-01", "otra-01")
    assert r["periodo"] is None
    assert r["variables"] == {}
    assert r["observacion"]


def test_comparar_una_estacion_consigo_misma_falla(estacion):
    with pytest.raises(ValueError):
        comparar_estaciones("prueba-01", "prueba-01")


def test_periodo_invertido_falla(estacion, otra):
    with pytest.raises(ValueError):
        comparar_estaciones("prueba-01", "otra-01", date(2024, 2, 1), date(2024, 1, 1))
