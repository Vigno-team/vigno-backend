"""Contrato HTTP y calidad de los resultados de E1C-46/E1C-47."""

from datetime import date, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from drf_spectacular.generators import SchemaGenerator

from apps.clima.indices import calcular_indices_temporada
from apps.clima.models import ConfiguracionCalidad, Estacion, IndiceClimatico, ResumenDiario
from apps.clima.temporadas import temporada_de

pytestmark = pytest.mark.django_db


@pytest.fixture
def estacion():
    return Estacion.objects.create(
        nombre="Estación de prueba", codigo="prueba-01", subzona="cauquenes", latitud=-35.52
    )


def cargar_dias(estacion, inicio, cantidad, **datos):
    ResumenDiario.objects.bulk_create(
        ResumenDiario(
            estacion=estacion,
            fecha=inicio + timedelta(days=i),
            temporada=temporada_de(inicio + timedelta(days=i)),
            **datos,
        )
        for i in range(cantidad)
    )


def consultar(client, estacion, temporada="2024-2025", recurso="temporadas"):
    return client.get(f"/api/v1/{recurso}/{temporada}", {"estacion": estacion.codigo})


def test_ficha_entrega_resultados_del_pipeline_y_respeta_contrato(client, estacion):
    # Winkler = 212 * 10 = 2120, Huglin = 182 * 17.5 = 3185 con K=1.
    cargar_dias(estacion, date(2024, 10, 1), 212, tmedia=20, tmax=35, tmin=5)
    calcular_indices_temporada(estacion, "2024-2025")

    response = consultar(client, estacion)

    assert response.status_code == 200
    data = response.json()
    assert set(data) == {
        "temporada",
        "estacion_id",
        "subzona",
        "periodo",
        "indices",
        "lluvia_invernal",
        "calor",
        "clasificacion",
        "dias_criticos",
    }
    assert data["estacion_id"] == "prueba-01"
    assert data["periodo"] == {"inicio": "2024-10-01", "fin": "2025-04-30"}
    assert data["indices"]["winkler"]["valor"] == 2120
    assert data["indices"]["winkler"]["region"] == "IV"
    assert data["indices"]["huglin"]["valor"] == 3185
    assert data["indices"]["huglin"]["clasificacion"] == "muy calido"
    for tipo in ("winkler", "huglin"):
        calidad = data["indices"][tipo]["calidad_dato"]
        assert calidad["completitud_pct"] == 100
        assert calidad["confiable"] is True
        assert calidad["umbral_completitud_pct"] == 80
        assert calidad["resolucion_origen"] == "diaria"
        assert (
            calidad["version_calculo"]
            == IndiceClimatico.objects.get(estacion=estacion, indice=tipo.title()).version_calculo
        )
    assert data["calor"]["dias_sobre_umbral"] == 212
    assert len(data["dias_criticos"]) == 10
    assert data["clasificacion"] is None  # dependencia E1C-18


def test_baja_completitud_publica_valor_parcial_y_advertencia(client, estacion):
    cargar_dias(estacion, date(2024, 10, 1), 2, tmedia=20, tmax=30, tmin=10)
    calcular_indices_temporada(estacion, "2024-2025")

    indice = consultar(client, estacion).json()["indices"]["winkler"]

    assert indice["valor"] == 20
    assert indice["region"] is None
    assert indice["calidad_dato"]["completitud_pct"] == 0.9
    assert indice["calidad_dato"]["confiable"] is False


def test_faltantes_son_null_con_motivo_y_no_disparan_calculos(client, estacion):
    cargar_dias(estacion, date(2024, 10, 1), 1)

    data = consultar(client, estacion).json()

    for tipo in ("winkler", "huglin"):
        assert data["indices"][tipo]["valor"] is None
        assert data["indices"][tipo]["motivo_nulo"]
        assert data["indices"][tipo]["calidad_dato"]["completitud_pct"] is None
        assert data["indices"][tipo]["calidad_dato"]["version_calculo"] is None
        assert data["indices"][tipo]["calidad_dato"]["confiable"] is False
    assert data["lluvia_invernal"]["acumulado_mm"] is None
    assert data["lluvia_invernal"]["motivo_nulo"]
    assert data["calor"]["dias_sobre_umbral"] is None
    assert data["calor"]["racha_maxima_dias"] is None
    assert data["calor"]["motivo_nulo"]
    assert data["dias_criticos"] == []
    assert not IndiceClimatico.objects.exists()
    assert not ConfiguracionCalidad.objects.exists()


def test_un_indice_no_calculado_no_se_sustituye_con_datos_de_ejemplo(client, estacion):
    cargar_dias(estacion, date(2024, 10, 1), 1, tmedia=20, tmax=30)
    data = consultar(client, estacion).json()
    assert data["indices"]["winkler"]["valor"] is None
    assert data["indices"]["huglin"]["valor"] is None


def test_ausencia_no_es_confiable_incluso_con_umbral_cero(client, estacion):
    ConfiguracionCalidad.objects.create(umbral_pct=0)
    cargar_dias(estacion, date(2024, 10, 1), 1)
    data = consultar(client, estacion).json()
    for bloque in (data["lluvia_invernal"], data["calor"], *data["indices"].values()):
        assert bloque["calidad_dato"]["confiable"] is False


def test_cero_observado_se_distingue_de_ausencia(client, estacion):
    cargar_dias(estacion, date(2024, 10, 1), 1, tmedia=5, tmax=8, tmin=2)
    cargar_dias(estacion, date(2024, 5, 1), 123, precipitacion=0)
    calcular_indices_temporada(estacion, "2024-2025")
    data = consultar(client, estacion).json()
    assert data["indices"]["winkler"]["valor"] == 0
    assert data["lluvia_invernal"]["acumulado_mm"] == 0
    assert data["calor"]["dias_sobre_umbral"] == 0
    assert data["calor"]["rachas_con_incidencia"] == 0
    assert data["calor"]["racha_maxima_dias"] == 0


def test_lluvia_usa_invierno_y_promedio_historico_real(client, estacion):
    for anio, mm in ((2022, 1), (2023, 2), (2024, 3)):
        cargar_dias(estacion, date(anio, 5, 1), 123, precipitacion=mm)

    lluvia = consultar(client, estacion).json()["lluvia_invernal"]

    assert lluvia["acumulado_mm"] == 369
    assert lluvia["promedio_historico_mm"] == 246
    assert lluvia["diferencia_pct"] == 50
    assert lluvia["calidad_dato"]["completitud_pct"] == 100
    assert lluvia["calidad_dato"]["confiable"] is True


def test_aisla_estacion_temporada_y_limita_dias_criticos(client, estacion):
    otra = Estacion.objects.create(nombre="Otra", codigo="otra")
    cargar_dias(otra, date(2024, 10, 1), 20, tmax=60)
    cargar_dias(estacion, date(2023, 10, 1), 20, tmax=50)
    for i in range(12):
        cargar_dias(estacion, date(2024, 10, 1) + timedelta(days=i), 1, tmax=20 + i)
    data = consultar(client, estacion).json()
    assert [d["tmax"] for d in data["dias_criticos"]] == list(range(31, 21, -1))
    assert all(d["fecha"].startswith("2024-") for d in data["dias_criticos"])
    assert data["calor"]["dias_sobre_umbral"] == 0


def test_rachas_no_unen_dias_separados_por_faltantes(client, estacion):
    cargar_dias(estacion, date(2024, 10, 1), 5, tmax=35)
    cargar_dias(estacion, date(2024, 10, 7), 2, tmax=36)
    data = consultar(client, estacion, recurso="rachas").json()
    assert [r["dias"] for r in data["rachas"]] == [5, 2]
    assert [r["con_incidencia"] for r in data["rachas"]] == [True, False]
    assert data["rachas"][0]["inicio"] == "2024-10-01"
    assert data["rachas"][1]["interrumpida_por_dato_faltante"] is True
    assert data["calidad_dato"]["confiable"] is False


def test_umbrales_configurables_coinciden_en_ficha_y_rachas(client, estacion, settings):
    settings.UMBRAL_CALOR_C = 30
    settings.MINIMO_DIAS_INCIDENCIA = 2
    cargar_dias(estacion, date(2024, 10, 1), 3, tmax=31)
    ficha = consultar(client, estacion).json()
    detalle = consultar(client, estacion, recurso="rachas").json()
    assert ficha["calor"]["umbral_c"] == detalle["umbral_c"] == 30
    assert detalle["minimo_dias_incidencia"] == 2
    assert ficha["calor"]["dias_sobre_umbral"] == 3
    assert ficha["calor"]["rachas_con_incidencia"] == 1
    assert "30c_min2" in detalle["calidad_dato"]["version_calculo"]


def test_no_promueve_huglin_sin_latitud_al_bajar_umbral(client, estacion):
    estacion.latitud = None
    estacion.save(update_fields=["latitud"])
    ConfiguracionCalidad.objects.create(umbral_pct=0)
    cargar_dias(estacion, date(2024, 10, 1), 1, tmedia=20, tmax=30)
    calcular_indices_temporada(estacion, "2024-2025")
    data = consultar(client, estacion).json()
    assert data["indices"]["winkler"]["calidad_dato"]["confiable"] is True
    assert data["indices"]["huglin"]["calidad_dato"]["confiable"] is False


def test_umbral_actual_mas_exigente_rechaza_indice_previamente_confiable(client, estacion):
    config = ConfiguracionCalidad.objects.create(umbral_pct=0)
    cargar_dias(estacion, date(2024, 10, 1), 2, tmedia=20, tmax=30)
    calcular_indices_temporada(estacion, "2024-2025")
    config.umbral_pct = 80
    config.save()
    calidad = consultar(client, estacion).json()["indices"]["winkler"]["calidad_dato"]
    assert calidad["umbral_completitud_pct"] == 80
    assert calidad["confiable"] is False


def test_resolucion_mixta_se_determina_por_periodo_del_indice(client, estacion):
    cargar_dias(estacion, date(2024, 10, 1), 1, tmedia=20, tmax=30, origen="H")
    cargar_dias(estacion, date(2024, 10, 2), 1, tmedia=20, tmax=30, origen="D")
    calcular_indices_temporada(estacion, "2024-2025")
    calidad = consultar(client, estacion).json()["indices"]["winkler"]["calidad_dato"]
    assert calidad["resolucion_origen"] == "mixta"


@pytest.mark.parametrize("recurso", ["temporadas", "rachas"])
@pytest.mark.parametrize("temporada", ["2024", "aaaa-bbbb", "2024-2026", "2025-2024", "0000-0001"])
def test_temporada_invalida_devuelve_400(client, estacion, recurso, temporada):
    response = consultar(client, estacion, temporada, recurso)
    assert response.status_code == 400
    assert "temporada" in response.json()


@pytest.mark.parametrize("recurso", ["temporadas", "rachas"])
@pytest.mark.parametrize("parametros", [{}, {"estacion": ""}, {"estacion": " "}])
def test_estacion_obligatoria(client, recurso, parametros):
    response = client.get(f"/api/v1/{recurso}/2024-2025", parametros)
    assert response.status_code == 400
    assert "estacion" in response.json()


@pytest.mark.parametrize("recurso", ["temporadas", "rachas"])
def test_estacion_o_temporada_sin_registros_devuelve_404(client, estacion, recurso):
    assert client.get(f"/api/v1/{recurso}/2024-2025", {"estacion": "no-existe"}).status_code == 404
    assert consultar(client, estacion, recurso=recurso).status_code == 404


def test_catalogos_y_fechas_solo_con_datos(client, estacion):
    cargar_dias(estacion, date(2023, 1, 1), 1)
    cargar_dias(estacion, date(2024, 10, 1), 1, tmax=20, tmin=10)
    assert client.get("/api/v1/temporadas").json() == ["2024-2025"]
    data = next(e for e in client.get("/api/v1/estaciones").json() if e["id"] == estacion.codigo)
    assert data["id"] == estacion.codigo
    assert data["fecha_inicio"] == data["fecha_fin"] == "2024-10-01"
    assert data["calidad_dato"]["completitud_pct"] == 100


@pytest.mark.parametrize(
    "path", ["estaciones", "temporadas", "temporadas/2024-2025", "rachas/2024-2025"]
)
def test_solo_lectura_y_sin_escrituras_por_get(client, estacion, path):
    cargar_dias(estacion, date(2024, 10, 1), 1, tmax=30)
    with CaptureQueriesContext(connection) as queries:
        response = client.get(f"/api/v1/{path}", {"estacion": estacion.codigo})
    assert response.status_code == 200
    assert not any(
        q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries
    )
    assert client.post(f"/api/v1/{path}", {}).status_code == 405


def test_openapi_incluye_consultas_y_metadatos():
    schema = SchemaGenerator().get_schema(public=True)
    for path in (
        "/api/v1/estaciones",
        "/api/v1/temporadas",
        "/api/v1/temporadas/{temporada}",
        "/api/v1/rachas/{temporada}",
    ):
        assert path in schema["paths"]
    get = schema["paths"]["/api/v1/temporadas/{temporada}"]["get"]
    assert next(p for p in get["parameters"] if p["name"] == "estacion")["required"] is True
    assert {"200", "400", "404"} <= set(get["responses"])
    calidad = schema["components"]["schemas"]["CalidadDato"]
    assert set(calidad["properties"]) == {
        "completitud_pct",
        "confiable",
        "umbral_completitud_pct",
        "resolucion_origen",
        "version_calculo",
    }


def test_ficha_clasifica_la_temporada_con_criterio_explicito(client, estacion):
    for anio in (2021, 2022, 2023):
        cargar_dias(estacion, date(anio, 10, 1), 212, tmedia=20)
    cargar_dias(estacion, date(2024, 10, 1), 212, tmedia=22)
    for anio, mm in ((2021, 2), (2022, 2), (2023, 2), (2024, 3)):
        cargar_dias(estacion, date(anio, 5, 1), 123, precipitacion=mm)

    clasificacion = consultar(client, estacion).json()["clasificacion"]

    assert clasificacion["termica"] == "calida"
    assert clasificacion["hidrica"] == "lluviosa"
    assert "Winkler" in clasificacion["criterio"] and "mayo-agosto" in clasificacion["criterio"]


def test_ficha_no_clasifica_si_falta_un_eje(client, estacion):
    for anio in (2021, 2022, 2023, 2024):
        cargar_dias(estacion, date(anio, 10, 1), 212, tmedia=20)  # sin datos de lluvia
    assert consultar(client, estacion).json()["clasificacion"] is None
