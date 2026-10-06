"""Datos sintéticos: contratos, cálculos conocidos e integración de solo lectura."""

import copy
import json
from datetime import date, timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.clima.analisis_cosecha import generar_informe
from apps.clima.models import ConfiguracionCalidad, Estacion, IndiceClimatico
from apps.ml.correlaciones import analizar_objetivo, correlacion
from apps.ml.historico import validar_historico


def historico(n=5):
    return {
        "version": "1",
        "escala_calidad": {
            "nombre": "Puntaje SINTÉTICO",
            "tipo": "numerica",
            "minimo": 0,
            "maximo": 100,
        },
        "registros": [
            {
                "subzona": "Prueba",
                "cepa": "Prueba",
                "temporada": f"{2018+i}-{2019+i}",
                "fecha_cosecha": (date(2018 + i, 7, 1) + timedelta(days=250 - i * 5)).isoformat(),
                "calidad": 60 + i * 5,
            }
            for i in range(n)
        ],
    }


@pytest.mark.parametrize(
    "x,y,rho,p",
    [
        ([1, 2, 3], [3, 2, 1], -1, 1 / 3),
        ([1, 2, 3, 4, 5], [1, 2, 3, 4, 5], 1, 1 / 60),
        ([1, 1, 2], [1, 1, 2], 1, 1 / 3),
        ([1, 2, 3], [1, 3, 2], 0.5, 1),
    ],
)
def test_coeficientes_y_p_exactos_conocidos(x, y, rho, p):
    resultado = correlacion(x, y)
    assert resultado["rho"] == pytest.approx(rho)
    assert resultado["p_valor"] == pytest.approx(p)
    assert resultado["prueba"] == "permutacion_exacta"


def test_spearman_con_empates_referencia_scipy():
    # Ejemplo oficial scipy.stats.spearmanr 1.14.1: rho=0.7.
    resultado = correlacion(
        [7.1, 7.1, 7.2, 8.3, 9.4, 10.5, 11.4], [2.8, 2.9, 2.8, 2.6, 3.5, 4.6, 5]
    )
    assert resultado["rho"] == pytest.approx(0.7)
    assert resultado["permutaciones"] == 5040


@pytest.mark.parametrize(
    "x,y,estado",
    [
        ([], [], "muestra_insuficiente"),
        ([1, 2], [2, 1], "muestra_insuficiente"),
        ([1, 1, 1], [2, 3, 4], "serie_constante"),
        ([1, 2, 3], [4, 4, 4], "serie_constante"),
    ],
)
def test_no_inventa_correlaciones(x, y, estado):
    resultado = correlacion(x, y)
    assert resultado["estado"] == estado
    assert resultado["rho"] is None and resultado["p_valor"] is None


@pytest.mark.parametrize(
    "x,y", [([1], []), ([float("nan")] * 3, [1] * 3), ([True] * 3, [1] * 3), ([None] * 3, [1] * 3)]
)
def test_rechaza_series_invalidas(x, y):
    with pytest.raises(ValueError):
        correlacion(x, y)


def test_permutacion_aleatoria_reproducible_y_p_no_cero():
    x = list(range(9))
    a = correlacion(x, x)
    b = correlacion(x, x)
    assert a == b
    assert a["prueba"] == "permutacion_monte_carlo"
    assert a["permutaciones"] == 9999 and 0 < a["p_valor"] <= 1


def test_ranking_utiliza_mismos_anios_signo_y_empates():
    objetivos = {str(i): i for i in range(5)}
    indices = {"A": objetivos, "B": {str(i): -i for i in range(4)}}
    salida = analizar_objetivo(objetivos, indices, {})
    assert salida["n_comun"] == 4
    assert [d["n"] for d in salida["diagnostico_por_indice"]] == [5, 4]
    assert [r["n"] for r in salida["ranking"]] == [4, 4]
    assert [r["rho"] for r in salida["ranking"]] == [1, -1]
    assert [r["posicion"] for r in salida["ranking"]] == [1, 1]
    assert [r["p_ajustado_holm"] for r in salida["ranking"]] == pytest.approx([1 / 6, 1 / 6])
    assert any("Histórico corto" in a for a in salida["advertencias"])


def test_no_compara_cohortes_sin_suficientes_anios_comunes():
    objetivos = {str(i): i for i in range(5)}
    indices = {"A": {str(i): i for i in range(3)}, "B": {str(i): i for i in range(2, 5)}}
    salida = analizar_objetivo(objetivos, indices, {})
    assert all(d["estado"] == "ok" for d in salida["diagnostico_por_indice"])
    assert salida["ranking"] == [] and salida["n_comun"] == 1


def test_no_ordena_si_constante_en_submuestra_comun():
    y = dict(enumerate(range(4)))
    salida = analizar_objetivo(y, {"A": {0: 1, 1: 1, 2: 1, 3: 4}, "B": {0: 2, 1: 3, 2: 4}}, {})
    assert salida["ranking"] == []
    assert "constante" in salida["motivo_sin_ranking"]


def test_fechas_son_dias_de_temporada_y_no_anios_absolutos():
    filas = validar_historico(historico())
    assert [f["dia_cosecha"] for f in filas] == [250, 245, 240, 235, 230]


@pytest.mark.parametrize(
    "campo,valor",
    [
        ("temporada", "2024-2026"),
        ("fecha_cosecha", "2017-05-01"),
        ("fecha_cosecha", "2019-02-30"),
        ("fecha_cosecha", "20190301"),
        ("calidad", True),
        ("calidad", float("nan")),
        ("calidad", 101),
        ("cepa", ""),
        ("subzona", None),
    ],
)
def test_valida_datos_historicos(campo, valor):
    datos = historico()
    datos["registros"][0][campo] = valor
    with pytest.raises(ValueError):
        validar_historico(datos)


def test_rechaza_duplicados_sin_agregarlos_silenciosamente():
    datos = historico()
    datos["registros"].append(copy.deepcopy(datos["registros"][0]))
    with pytest.raises(ValueError, match="duplicado"):
        validar_historico(datos)


def test_ordinal_respeta_orden_declarado_y_no_alfabetico():
    datos = historico(3)
    datos["escala_calidad"] = {
        "nombre": "SINTÉTICA",
        "tipo": "ordinal",
        "orden": ["baja", "media", "alta"],
    }
    for fila, categoria in zip(datos["registros"], ["alta", "media", "baja"], strict=True):
        fila["calidad"] = categoria
    assert [f["calidad_numerica"] for f in validar_historico(datos)] == [2, 1, 0]
    datos["registros"][0]["calidad"] = "desconocida"
    with pytest.raises(ValueError, match="desconocida"):
        validar_historico(datos)


@pytest.mark.parametrize(
    "escala",
    [
        None,
        {},
        {"nombre": "X", "tipo": "nominal"},
        {"nombre": "X", "tipo": "ordinal", "orden": ["alta", "alta"]},
        {"nombre": "X", "tipo": "numerica", "minimo": 100, "maximo": 0},
    ],
)
def test_escala_de_calidad_debe_estar_declarada(escala):
    datos = historico()
    datos["escala_calidad"] = escala
    with pytest.raises(ValueError):
        validar_historico(datos)


@pytest.fixture
def estacion(db):
    estacion = Estacion.objects.create(nombre="Prueba", codigo="test", subzona="Prueba")
    for i, fila in enumerate(historico()["registros"]):
        for nombre, valor in [("Winkler", 1000 + i * 100), ("Huglin", 1500 - i * 100)]:
            IndiceClimatico.objects.create(
                estacion=estacion,
                temporada=fila["temporada"],
                indice=nombre,
                valor=valor,
                confiable=True,
                dias_con_dato=200,
                dias_esperados=212,
                version_calculo=f"{nombre}-v1",
                parametros={
                    "fecha_inicio": f"{2018+i}-10-01",
                    "fecha_fin": f"{2019+i}-04-30",
                    "completitud_pct": 94.34,
                    "temp_base": 10,
                },
            )
    return estacion


def test_informe_join_real_sin_escrituras_y_con_trazabilidad(estacion):
    with CaptureQueriesContext(connection) as consultas:
        informe = generar_informe(historico(), estacion, "Prueba")
    assert not any(
        q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in consultas
    )
    assert ConfiguracionCalidad.objects.count() == 0
    assert informe["n_registros_cohorte"] == 5
    assert len(informe["indices_origen"]) == 10
    assert len(informe["historico_sha256"]) == 64
    fecha = informe["resultados"]["fecha_cosecha"]
    calidad = informe["resultados"]["calidad"]
    assert fecha["n_comun"] == calidad["n_comun"] == 5
    assert {r["indice"]: r["rho"] for r in fecha["ranking"]} == {"Winkler": -1, "Huglin": 1}
    assert {r["indice"]: r["rho"] for r in calidad["ranking"]} == {"Winkler": 1, "Huglin": -1}
    json.dumps(informe, allow_nan=False)


def test_calidad_ausente_no_descarta_fecha_y_cero_es_valido(estacion):
    datos = historico()
    datos["registros"][0]["calidad"] = None
    datos["registros"][1]["calidad"] = 0
    informe = generar_informe(datos, estacion, "Prueba")["resultados"]
    assert informe["fecha_cosecha"]["n_comun"] == 5
    assert informe["calidad"]["n_comun"] == 4
    assert any(
        e["motivo"] == "objetivo_ausente"
        for e in informe["calidad"]["diagnostico_por_indice"][0]["exclusiones"]
    )


@pytest.mark.parametrize(
    "cambio,motivo",
    [
        ({"confiable": False}, "indice_no_confiable"),
        ({"dias_con_dato": 20}, "completitud_insuficiente"),
        ({"dias_esperados": 0}, "conteos_invalidos"),
        ({"version_calculo": None}, "metodologia_ausente_o_invalida"),
    ],
)
def test_excluye_indices_inutilizables(estacion, cambio, motivo):
    IndiceClimatico.objects.filter(
        estacion=estacion, temporada="2018-2019", indice="Winkler"
    ).update(**cambio)
    informe = generar_informe(historico(), estacion, "Prueba")["resultados"]["calidad"]
    assert informe["n_comun"] == 4
    detalle = next(d for d in informe["diagnostico_por_indice"] if d["indice"] == "Winkler")
    assert detalle["exclusiones"] == [{"temporada": "2018-2019", "motivo": motivo}]


@pytest.mark.parametrize("cambio", [{"version_calculo": "v2"}, {"parametros": {"temp_base": 15}}])
def test_no_mezcla_versiones_o_parametros(estacion, cambio):
    IndiceClimatico.objects.filter(indice="Huglin", temporada="2018-2019").update(**cambio)
    informe = generar_informe(historico(), estacion, "Prueba")["resultados"]["calidad"]
    detalle = next(d for d in informe["diagnostico_por_indice"] if d["indice"] == "Huglin")
    assert detalle["n"] == 0 and informe["ranking"] == []
    assert {e["motivo"] for e in detalle["exclusiones"]} == {"metodologias_incompatibles"}


def test_no_mezcla_otras_cepas_o_subzonas(estacion):
    datos = historico()
    otra = copy.deepcopy(datos["registros"][0])
    otra["cepa"] = "Otra"
    datos["registros"].append(otra)
    informe = generar_informe(datos, estacion, "Prueba")
    assert informe["n_registros_cohorte"] == 5 and informe["n_registros_otras_cohortes"] == 1
    with pytest.raises(ValueError, match="coincidan"):
        generar_informe(datos, estacion, "Inexistente")


def test_sin_indices_reales_falla_sin_datos_de_relleno(estacion):
    IndiceClimatico.objects.all().delete()
    with pytest.raises(ValueError, match="No hay índices"):
        generar_informe(historico(), estacion, "Prueba")


def test_indice_ausente_se_informa_y_reduce_la_muestra_comun(estacion):
    IndiceClimatico.objects.filter(indice="Winkler", temporada="2018-2019").delete()
    salida = generar_informe(historico(), estacion, "Prueba")["resultados"]["calidad"]
    assert salida["n_comun"] == 4
    detalle = next(d for d in salida["diagnostico_por_indice"] if d["indice"] == "Winkler")
    assert detalle["exclusiones"] == [{"temporada": "2018-2019", "motivo": "indice_ausente"}]


def test_aplica_umbral_actual_aunque_indice_almacenado_diga_confiable(estacion):
    ConfiguracionCalidad.objects.create(umbral_pct=95)
    salida = generar_informe(historico(), estacion, "Prueba")["resultados"]["calidad"]
    assert salida["ranking"] == []
    assert all(d["n"] == 0 for d in salida["diagnostico_por_indice"])


def test_fecha_ausente_no_descarta_calidad(estacion):
    datos = historico()
    for fila in datos["registros"]:
        fila["fecha_cosecha"] = None
    salida = generar_informe(datos, estacion, "Prueba")["resultados"]
    assert salida["fecha_cosecha"]["ranking"] == []
    assert salida["calidad"]["n_comun"] == 5


def test_cli_rechaza_plantilla_vacia_sin_crear_salida(estacion, tmp_path):
    entrada = tmp_path / "vacio.json"
    salida = tmp_path / "salida.json"
    entrada.write_text('{"version": "1", "escala_calidad": null, "registros": []}')
    with pytest.raises(CommandError, match="escala_calidad"):
        call_command(
            "analizar_correlaciones",
            historico=str(entrada),
            salida=str(salida),
            estacion="test",
            cepa="Prueba",
        )
    assert not salida.exists()


def test_cli_exporta_json_y_no_sobrescribe_archivos(estacion, tmp_path):
    entrada = tmp_path / "historico.json"
    salida = tmp_path / "salida.json"
    entrada.write_text(json.dumps(historico()), encoding="utf-8-sig")
    opciones = {
        "historico": str(entrada),
        "salida": str(salida),
        "estacion": "test",
        "cepa": "Prueba",
    }
    call_command("analizar_correlaciones", **opciones)
    original = salida.read_bytes()
    assert json.loads(original)["version"] == "e1c20-v1"
    with pytest.raises(CommandError):
        call_command("analizar_correlaciones", **opciones)
    assert salida.read_bytes() == original
    with pytest.raises(CommandError):
        call_command("analizar_correlaciones", **{**opciones, "salida": str(entrada)})
    assert json.loads(entrada.read_text(encoding="utf-8-sig")) == historico()
