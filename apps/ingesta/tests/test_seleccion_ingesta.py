"""Selección por variable, calidad de columnas y procedencia de las mediciones."""

import pandas as pd
import pytest

from apps.clima.mapeos import estacion_y_mapeo
from apps.clima.models import MedicionHoraria
from apps.clima.tests.test_ingestar_excel import crear_excel, fila
from apps.ingesta import carga
from apps.ingesta.variables import DEPENDENCIAS_INDICADORES, catalogo_variables

pytestmark = pytest.mark.django_db


def preparar(tmp_path, filas=None):
    ruta = crear_excel(tmp_path / "archivo_2025.xlsx", filas or [fila("2025-01-10")])
    estacion, mapeo = estacion_y_mapeo("San Clemente")
    return carga.preparar(ruta, "archivo_2025.xlsx", estacion, mapeo)


def guardar(prep, variables=None):
    return carga.guardar(
        prep,
        carga.clasificar(prep, variables),
        "archivo_2025.xlsx",
        variables=variables,
    )


def test_diagnostico_distingue_vacias_no_numericas_y_fuera_de_rango(tmp_path):
    prep = preparar(tmp_path)
    columna = prep.map_cols["temperatura_media"]
    prep.limpieza.crudo = pd.DataFrame(
        {nombre: [20, None, " ", "error", 80, float("inf")] for nombre in prep.limpieza.crudo}
    )
    diagnostico = next(
        dato
        for dato in carga.diagnosticar_columnas(prep)
        if dato["variable"] == "temperatura_media"
    )
    assert diagnostico == {
        "variable": "temperatura_media",
        "columna": columna,
        "filas_total": 6,
        "filas_con_dato": 4,
        "filas_vacias": 2,
        "filas_no_numericas": 2,
        "filas_fuera_de_rango": 1,
        "filas_validas": 1,
        "porcentaje_valido": 16.67,
        "indicadores": ["winkler", "huglin", "clasificacion", "anos_analogos", "prediccion"],
    }


@pytest.mark.parametrize("variables", [[], "humedad_media", [None], ["timestamp"], ["invalida"]])
def test_rechaza_seleccion_invalida(tmp_path, variables):
    prep = preparar(tmp_path)
    with pytest.raises(carga.ErrorCarga):
        carga.seleccionar_variables(prep, variables)


def test_seleccion_humedad_omite_umbrales_temperatura_y_no_guarda_otros_datos(tmp_path):
    filas = [fila("2025-01-10", "error"), fila("2025-01-11", None)]
    for valores in filas:
        valores[2] = valores[3] = None
    prep = preparar(tmp_path, filas)
    assert carga.validar_umbrales(prep, carga.cargar_umbrales())
    assert carga.validar_umbrales(prep, carga.cargar_umbrales(), ["humedad_media"]) == []
    registro = guardar(prep, ["humedad_media"])
    assert registro.variables_procesadas == ["humedad_media"]
    assert set(registro.variables_excluidas) == set(prep.map_cols) - {"timestamp", "humedad_media"}
    assert list(MedicionHoraria.objects.values_list("variable", "valor", "carga_id")) == [
        ("humedad_media", 50, registro.pk),
        ("humedad_media", 50, registro.pk),
    ]


def test_columna_no_elegida_no_modifica_valor_ni_carga_previos(tmp_path):
    original = guardar(preparar(tmp_path))
    medicion = MedicionHoraria.objects.get(variable="temperatura_media")
    registro = guardar(preparar(tmp_path, [fila("2025-01-10", 35)]), ["humedad_media"])
    medicion.refresh_from_db()
    assert medicion.valor == 15
    assert medicion.carga == original
    assert not registro.mediciones_generadas.exists()  # La humedad idéntica conserva su origen.


def test_reactivar_medicion_por_nueva_carga_actualiza_su_procedencia(tmp_path):
    original = guardar(preparar(tmp_path), ["humedad_media"])
    original.mediciones_generadas.update(excluido=True)
    nueva = guardar(preparar(tmp_path), ["humedad_media"])
    medicion = MedicionHoraria.objects.get(variable="humedad_media")
    assert medicion.carga == nueva
    assert medicion.excluido is False
    assert nueva.registros_actualizados == 1


def test_incorporar_columnas_no_pisa_otras_cargas_ni_manual(tmp_path):
    prep = preparar(tmp_path)
    registro = guardar(prep, ["humedad_media"])
    otra = guardar(prep, ["temperatura_maxima"])
    maxima = otra.mediciones_generadas.get()
    maxima.origen = "manual"
    maxima.valor = 33
    maxima.save()

    incorporadas = carga.incorporar_variables(
        prep, registro, ["temperatura_media", "temperatura_maxima", "temperatura_minima"]
    )

    assert incorporadas == 2
    maxima.refresh_from_db()
    assert (maxima.carga_id, maxima.origen, maxima.valor) == (otra.pk, "manual", 33)
    assert set(registro.mediciones_generadas.values_list("variable", flat=True)) == {
        "humedad_media",
        "temperatura_media",
        "temperatura_minima",
    }


def test_no_finitos_y_blancos_no_se_guardan_como_numeros(tmp_path):
    prep = preparar(tmp_path)
    columna = prep.map_cols["temperatura_media"]
    crudo = pd.DataFrame({"fecha": ["2025-01-10"], columna: ["inf"]})
    limpieza = carga.limpiar_y_rechazar(
        crudo, {"timestamp": "fecha", "temperatura_media": columna}, "D", "America/Santiago", 0
    )
    assert pd.isna(limpieza.df_limpio.iloc[0][columna])
    prep.limpieza.df_limpio[columna] = float("nan")
    prep.limpieza.crudo[columna] = " "
    registro = guardar(prep, ["temperatura_media"])
    medicion = registro.mediciones_generadas.get()
    assert medicion.valor is None
    assert medicion.motivo_nulo == "Dato en blanco en origen"


def test_catalogo_explica_alternativas_y_variables_solo_visuales():
    catalogo = {item["variable"]: item for item in catalogo_variables()}
    assert DEPENDENCIAS_INDICADORES["winkler"] == [
        ["temperatura_media"],
        ["temperatura_maxima", "temperatura_minima"],
    ]
    assert catalogo["humedad_media"]["unidad"] == "%"
    assert catalogo["humedad_media"]["indicadores"] == []
    assert "huglin" not in catalogo["precipitacion"]["indicadores"]
    assert "prediccion" in catalogo["precipitacion"]["indicadores"]
