import json
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.clima.areas_mapa import AreasMapaError, cargar_areas, cargar_geometria_predio
from apps.clima.models import Estacion

# Cuadrado de ~1 km cerca de Cauquenes, en [longitud, latitud].
ANILLO = [
    [-72.36, -35.53],
    [-72.35, -35.53],
    [-72.35, -35.52],
    [-72.36, -35.52],
    [-72.36, -35.53],
]


def feature(codigo="prueba-01", lat=-35.525, lon=-72.355, anillo=ANILLO, geometry="auto"):
    if geometry == "auto":
        geometry = {"type": "Polygon", "coordinates": [anillo]}
    return {
        "type": "Feature",
        "properties": {"codigo": codigo, "latitud": lat, "longitud": lon},
        "geometry": geometry,
    }


def escribir(tmp_path, *features):
    ruta = tmp_path / "areas.json"
    ruta.write_text(json.dumps({"type": "FeatureCollection", "features": list(features)}))
    return ruta


def test_archivo_valido(tmp_path):
    areas = cargar_areas(escribir(tmp_path, feature()))
    assert areas[0].codigo == "prueba-01"
    assert (areas[0].latitud, areas[0].longitud) == (-35.525, -72.355)
    assert areas[0].estacion_dentro


def test_config_real_carga_el_contorno_san_clemente():
    from django.conf import settings

    geometria = cargar_geometria_predio(
        settings.BASE_DIR / "config" / "areas_mapa.json", "cp-san-clemente-01"
    )

    anillo = geometria["coordinates"][0]
    assert geometria["type"] == "Polygon"
    assert len(anillo) == 27
    assert anillo[0] == anillo[-1]


def test_contorno_faltante_se_informa_por_predio(tmp_path):
    ruta = escribir(tmp_path, feature("sin-geom", geometry=None))
    with pytest.raises(AreasMapaError, match="sin-geom.*geometry es null"):
        cargar_geometria_predio(ruta, "sin-geom")

    with pytest.raises(AreasMapaError, match="No existe el predio no-existe"):
        cargar_geometria_predio(ruta, "no-existe")


def test_estacion_fuera_del_contorno_no_es_error(tmp_path):
    areas = cargar_areas(escribir(tmp_path, feature(lat=-35.60, lon=-72.30)))
    assert not areas[0].estacion_dentro


@pytest.mark.parametrize(
    "kwargs, texto",
    [
        ({"geometry": None}, "falta el contorno"),
        ({"lat": None}, "faltan las coordenadas"),
        ({"lat": -72.355, "lon": -35.525}, "fuera de Chile"),
        ({"anillo": ANILLO[:3]}, "al menos 4 puntos"),
        ({"anillo": ANILLO[:-1] + [[-72.37, -35.53]]}, "no está cerrado"),
        (
            {"geometry": {"type": "Point", "coordinates": [-72.35, -35.52]}},
            "Polygon o MultiPolygon",
        ),
        ({"lat": "-35.5"}, "debe ser un número"),
    ],
)
def test_archivo_invalido(tmp_path, kwargs, texto):
    with pytest.raises(AreasMapaError, match=texto):
        cargar_areas(escribir(tmp_path, feature(**kwargs)))


def test_codigo_duplicado_y_faltante(tmp_path):
    sin_codigo = feature()
    del sin_codigo["properties"]["codigo"]
    with pytest.raises(AreasMapaError) as exc:
        cargar_areas(escribir(tmp_path, feature(), feature(), sin_codigo))
    assert "más de una vez" in str(exc.value)
    assert "falta properties.codigo" in str(exc.value)


def test_json_roto_y_no_featurecollection(tmp_path):
    ruta = tmp_path / "malo.json"
    ruta.write_text("{")
    with pytest.raises(AreasMapaError, match="no es un JSON válido"):
        cargar_areas(ruta)
    ruta.write_text('{"type": "Feature"}')
    with pytest.raises(AreasMapaError, match="FeatureCollection"):
        cargar_areas(ruta)


CODIGOS_CONOCIDOS = {"cp-villavicencio-01", "cp-san-clemente-01"}


def test_config_versionada_es_valida_y_usa_codigos_conocidos():
    from django.conf import settings

    areas = cargar_areas(settings.BASE_DIR / "config" / "areas_mapa.json")
    assert areas, "El archivo versionado debe tener al menos un predio."
    assert {a.codigo for a in areas} <= CODIGOS_CONOCIDOS


@pytest.mark.django_db
def test_comando_actualiza_latitud_y_longitud(tmp_path):
    Estacion.objects.create(nombre="Prueba", codigo="prueba-01", latitud=-35.52)
    ruta = escribir(tmp_path, feature())
    call_command("cargar_areas_mapa", archivo=str(ruta), stdout=StringIO())
    est = Estacion.objects.get(codigo="prueba-01")
    assert (est.latitud, est.longitud) == (-35.525, -72.355)
    # Idempotente
    call_command("cargar_areas_mapa", archivo=str(ruta), stdout=StringIO())
    assert Estacion.objects.get(codigo="prueba-01").longitud == -72.355


@pytest.mark.django_db
def test_comando_solo_validar_no_escribe(tmp_path):
    Estacion.objects.create(nombre="Prueba", codigo="prueba-01", latitud=-35.52)
    call_command(
        "cargar_areas_mapa",
        archivo=str(escribir(tmp_path, feature())),
        solo_validar=True,
        stdout=StringIO(),
    )
    est = Estacion.objects.get(codigo="prueba-01")
    assert (est.latitud, est.longitud) == (-35.52, None)


@pytest.mark.django_db
def test_comando_falla_con_codigo_desconocido(tmp_path):
    Estacion.objects.create(nombre="Prueba", codigo="prueba-01")
    with pytest.raises(CommandError, match="otro-99"):
        call_command(
            "cargar_areas_mapa",
            archivo=str(escribir(tmp_path, feature("otro-99"))),
            stdout=StringIO(),
        )


@pytest.mark.django_db
def test_comando_avisa_estacion_sin_contorno(tmp_path):
    Estacion.objects.create(nombre="Prueba", codigo="prueba-01")
    Estacion.objects.create(nombre="Otra", codigo="otra-01")
    salida = StringIO()
    call_command("cargar_areas_mapa", archivo=str(escribir(tmp_path, feature())), stdout=salida)
    assert "sin contorno" in salida.getvalue()
    assert "otra-01" in salida.getvalue()


@pytest.mark.django_db
def test_comando_carga_el_archivo_versionado():
    from django.conf import settings

    areas = cargar_areas(settings.BASE_DIR / "config" / "areas_mapa.json")
    for area in areas:
        # Las migraciones ya crean las estaciones reales: se parte de la latitud vieja.
        Estacion.objects.update_or_create(
            codigo=area.codigo,
            defaults={"latitud": -35.52, "longitud": None},
            create_defaults={"nombre": area.codigo, "latitud": -35.52},
        )
    call_command("cargar_areas_mapa", stdout=StringIO())
    for area in areas:
        est = Estacion.objects.get(codigo=area.codigo)
        assert (est.latitud, est.longitud) == (area.latitud, area.longitud)


@pytest.mark.django_db
def test_longitud_es_opcional():
    est = Estacion.objects.create(nombre="Sin lon", codigo="sin-lon", latitud=-35.5)
    est.refresh_from_db()
    assert est.longitud is None
