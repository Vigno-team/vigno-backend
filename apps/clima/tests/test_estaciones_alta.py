"""Test para dar de alta una localidad nueva y cargarle su Excel con el formato estándar."""

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from rest_framework.test import APIClient

from apps.clima import mapeos
from apps.clima.estaciones import en_chile
from apps.clima.management.commands.exportar_json import exportar
from apps.clima.models import Estacion, MedicionHoraria
from apps.clima.tests.test_ingestar_excel import crear_excel, fila
from apps.ingesta.models import RegistroCarga

pytestmark = pytest.mark.django_db

URL = "/api/v1/estaciones"
CLAVE = "clave-de-prueba"
NUEVA = {"nombre": "Villa Nueva", "latitud": -35.9, "longitud": -72.3}


@pytest.fixture(autouse=True)
def clave(settings):
    settings.INGESTA_API_KEY = CLAVE


@pytest.fixture
def api():
    return APIClient(HTTP_X_API_KEY=CLAVE)


def crear(api, **cambios):
    return api.post(URL, {**NUEVA, **cambios}, format="json")


def en_get(client, codigo):
    return next(e for e in client.get(URL).json() if e["id"] == codigo)


# --- POST /api/v1/estaciones ---------------------------------------------------------------


def test_crea_la_estacion_y_responde_201(api):
    r = crear(api, subzona="cauquenes", propietario="Viña Nueva")

    assert r.status_code == 201
    cuerpo = r.json()
    assert cuerpo == {
        "id": "villa-nueva",
        "nombre": "Villa Nueva",
        "subzona": "cauquenes",
        "propietario": "Viña Nueva",
        "latitud": -35.9,
        "longitud": -72.3,
    }
    estacion = Estacion.objects.get(nombre="Villa Nueva")
    assert estacion.codigo == "villa-nueva"
    assert (estacion.latitud, estacion.longitud) == (-35.9, -72.3)


def test_subzona_y_propietario_son_opcionales(api):
    r = crear(api, subzona="", propietario=None)

    assert r.status_code == 201
    assert r.json()["subzona"] is None and r.json()["propietario"] is None


def test_codigo_sin_tildes_y_nombres_distintos_que_dan_el_mismo_codigo(api):
    # la puntuación hace distinto al nombre, pero el código se repetiría: se elige otro libre
    assert crear(api, nombre="Viña Álamos").json()["id"] == "vina-alamos"
    assert crear(api, nombre="Vina Alamos!").json()["id"] == "vina-alamos-2"
    assert crear(api, nombre="Vina-Alamos 2").json()["id"] == "vina-alamos-2-2"


@pytest.mark.parametrize("otro", ["villa nueva", "VILLA NUEVA", "Vílla  Nuéva ", " villa nueva"])
def test_nombre_repetido_sin_distinguir_mayusculas_ni_tildes_da_409(api, otro):
    crear(api)

    r = crear(api, nombre=otro, latitud=-36.0)

    assert r.status_code == 409
    assert r.json()["estacion"]["id"] == "villa-nueva"
    assert r.json()["estacion"]["nombre"] == "Villa Nueva"
    assert r.json()["estacion"]["latitud"] == -35.9  # la existente, no lo enviado
    assert Estacion.objects.filter(nombre__icontains="nueva").count() == 1


def test_409_tambien_con_las_estaciones_que_ya_existian(api):
    r = crear(api, nombre="Sán CLEMENTE")

    assert r.status_code == 409
    assert r.json()["estacion"]["id"] == Estacion.objects.get(nombre="San Clemente").codigo


@pytest.mark.parametrize(
    "lat, lon",
    [
        (-34.6, -58.4),  # Buenos Aires
        (-12.0, -77.0),  # Lima
        (35.9, -72.3),  # signo de latitud perdido
        (-72.3, -35.9),  # coordenadas cruzadas
        (0, 0),
        (-91, -72),
    ],
)
def test_coordenadas_fuera_de_chile_dan_400(api, lat, lon):
    r = crear(api, latitud=lat, longitud=lon)

    assert r.status_code == 400
    assert not Estacion.objects.filter(nombre="Villa Nueva").exists()


def test_coordenadas_cruzadas_sugieren_el_arreglo(api):
    r = crear(api, latitud=-72.3, longitud=-35.9)

    assert "Intercambiaste" in r.json()["coordenadas"][0]


@pytest.mark.parametrize(
    "cambios",
    [
        {"nombre": None},
        {"nombre": ""},
        {"nombre": "   "},
        {"nombre": "***"},
        {"nombre": "Formato estándar"},
        {"nombre": "formato_estandar"},
        {"nombre": "x" * 101},
        {"latitud": None},
        {"longitud": None},
        {"latitud": "abc"},
        {"latitud": "nan"},
        {"longitud": "inf"},
        {"subzona": "x" * 51},
    ],
)
def test_datos_incompletos_o_invalidos_dan_400(api, cambios):
    antes = Estacion.objects.count()

    r = crear(api, **cambios)

    assert r.status_code == 400
    assert Estacion.objects.count() == antes


@pytest.mark.parametrize("campo", ["nombre", "latitud", "longitud"])
def test_falta_un_campo_obligatorio_da_400(api, campo):
    datos = {k: v for k, v in NUEVA.items() if k != campo}

    r = api.post(URL, datos, format="json")

    assert r.status_code == 400
    assert campo in r.json()


def test_sin_clave_da_401(client):
    r = client.post(URL, NUEVA, content_type="application/json")

    assert r.status_code == 401
    assert not Estacion.objects.filter(nombre="Villa Nueva").exists()


def test_clave_incorrecta_da_401():
    r = APIClient(HTTP_X_API_KEY="otra").post(URL, NUEVA, format="json")

    assert r.status_code == 401


def test_sin_clave_configurada_nadie_escribe(settings):
    settings.INGESTA_API_KEY = ""

    assert APIClient(HTTP_X_API_KEY="").post(URL, NUEVA, format="json").status_code == 401
    assert APIClient(HTTP_X_API_KEY="x").post(URL, NUEVA, format="json").status_code == 401


def test_la_lectura_sigue_publica(client):
    assert client.get(URL).status_code == 200
    assert client.get(URL, HTTP_X_API_KEY="cualquiera").status_code == 200


def test_la_sin_clave_se_revisa_antes_que_los_datos(client):
    # 401 aunque el cuerpo sea inválido: no se filtra qué falta a quien no tiene clave
    assert client.post(URL, {}, content_type="application/json").status_code == 401


def test_cajas_de_chile():
    assert en_chile(-35.516667, -71.466667)  # San Clemente
    assert en_chile(-33.6, -78.8)  # Juan Fernández
    assert not en_chile(-34.6, -58.4)


# --- plantilla y búsqueda del mapeo ---------------------------------------------------------


def test_san_clemente_y_el_arenal_usan_la_plantilla():
    todos = mapeos.cargar_mapeos()
    estandar = todos[mapeos.PLANTILLA]

    assert "San Clemente" not in todos and "El Arenal" not in todos  # ya no están repetidos
    assert set(estandar["formatos"]) == {"A_2020_2022", "B_2023_2026"}
    assert mapeos.mapeo_de("San Clemente") == estandar
    assert mapeos.mapeo_de("el arenal") == estandar


def test_una_estacion_con_mapeo_propio_lo_conserva():
    propio = mapeos.mapeo_de("estacion horaria de PRUEBA")

    assert propio != mapeos.cargar_mapeos()[mapeos.PLANTILLA]
    assert set(propio["formatos"]) == {"H_prueba"}


def test_sin_plantilla_se_avisa():
    with pytest.raises(KeyError, match="formato_estandar"):
        mapeos.mapeo_de("Cualquiera", {})


# --- cargar un Excel a la estación nueva ----------------------------------------------------


def ingestar(archivo, nombre="Villa Nueva", **kwargs):
    call_command("ingestar_excel", archivo=archivo, estacion=nombre, **kwargs)


def test_carga_un_excel_con_el_formato_estandar_y_aparece_en_los_datos(api, client, tmp_path):
    codigo = crear(api).json()["id"]

    # recién creada: aparece, con coordenadas y vacía, y el JSON del frontend no se rompe
    vacia = en_get(client, codigo)
    assert (vacia["latitud"], vacia["longitud"]) == (-35.9, -72.3)
    assert vacia["variables"] == [] and vacia["fecha_inicio"] is None
    assert vacia["calidad_dato"]["completitud_pct"] is None
    assert codigo in [e["id"] for e in exportar()["estaciones"]]
    assert codigo not in [r["estacion_id"] for r in exportar()["resumen_diario"]]
    assert codigo in [m["estacion_id"] for m in exportar()["mapa_calor"]]

    archivo = crear_excel(
        tmp_path / "villa_nueva.xlsx",
        [fila("2025-09-07 00:00:00"), fila("2025-09-08 00:00:00", 16.0)],
    )
    ingestar(archivo, nombre="villa nueva")  # el nombre llega sin respetar mayúsculas

    carga = RegistroCarga.objects.get()
    assert carga.estacion == "Villa Nueva"
    assert carga.formato_detectado == "B_2023_2026"
    assert carga.estado == "OK" and carga.filas_aceptadas == 2
    assert MedicionHoraria.objects.filter(estacion__codigo=codigo).count() == 14

    call_command("generar_resumenes")
    datos = exportar()
    assert en_get(client, codigo)["fecha_inicio"] == "2025-09-07"
    assert [e for e in datos["estaciones"] if e["id"] == codigo][0]["variables"]
    resumen = next(r for r in datos["resumen_diario"] if r["estacion_id"] == codigo)
    assert [d["fecha"] for d in resumen["dias"]] == ["2025-09-07", "2025-09-08"]
    assert [m["estacion_id"] for m in datos["mapa_calor"]] == [e["id"] for e in datos["estaciones"]]


def test_ingestar_en_una_estacion_que_no_existe_pide_crearla(tmp_path):
    archivo = crear_excel(tmp_path / "x.xlsx", [fila("2025-09-07 00:00:00")])

    with pytest.raises(CommandError, match="La estación Fantasma no existe; créala primero"):
        ingestar(archivo, nombre="Fantasma")

    assert not Estacion.objects.filter(nombre="Fantasma").exists()  # ya no se crea al vuelo
    assert not RegistroCarga.objects.exists()


def test_san_clemente_sigue_cargando_con_su_mapeo(tmp_path):
    archivo = crear_excel(tmp_path / "sc.xlsx", [fila("2025-09-07 00:00:00")])

    ingestar(archivo, nombre="San Clemente")

    carga = RegistroCarga.objects.get()
    assert carga.estacion == "San Clemente" and carga.formato_detectado == "B_2023_2026"
    assert MedicionHoraria.objects.filter(estacion__nombre="San Clemente").count() == 7


def test_el_arenal_sigue_cargando_con_su_mapeo(tmp_path):
    archivo = crear_excel(tmp_path / "ea.xlsx", [fila("2025-09-07 00:00:00")])

    ingestar(archivo, nombre="El Arenal")

    assert RegistroCarga.objects.get().formato_detectado == "B_2023_2026"
    assert MedicionHoraria.objects.filter(estacion__nombre="El Arenal").count() == 7
