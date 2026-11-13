"""E1C-48: JSON para el frontend."""

import json
from datetime import date, timedelta

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.clima.indices import calcular_indices_temporada
from apps.clima.models import Estacion, IndiceClimatico, ResumenDiario
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


def dos_veranos(estacion):
    for anio in (2023, 2024):
        cargar_dias(estacion, date(anio, 10, 1), 212, tmedia=20, tmax=36, tmin=5)
        calcular_indices_temporada(estacion, f"{anio}-{anio + 1}")


def exportar(tmp_path, *args):
    salida = tmp_path / "datos.json"
    call_command("exportar_json", "--salida", str(salida), *args)
    return salida, json.loads(salida.read_text(encoding="utf-8"))


def test_exporta_los_bloques_del_contrato(tmp_path, estacion):
    dos_veranos(estacion)

    _, datos = exportar(tmp_path)

    assert set(datos) == {
        "generado",
        "temporada_en_curso",
        "estaciones",
        "temporadas",
        "completitud_por_temporada",
        "resumen_diario",
        "ficha_temporada",
        "rachas",
        "mapa_calor",
    }
    assert [f["temporada"] for f in datos["ficha_temporada"]] == ["2023-2024", "2024-2025"]
    assert [r["temporada"] for r in datos["rachas"]] == ["2023-2024", "2024-2025"]
    assert datos["ficha_temporada"][0]["indices"]["winkler"]["valor"] == 2120.0


def test_cada_bloque_es_igual_a_la_api(client, tmp_path, estacion):
    dos_veranos(estacion)

    _, datos = exportar(tmp_path)

    assert datos["estaciones"] == client.get("/api/v1/estaciones").json()
    assert datos["temporadas"] == client.get("/api/v1/temporadas").json()
    for ficha in datos["ficha_temporada"]:
        api = client.get(f"/api/v1/temporadas/{ficha['temporada']}", {"estacion": "prueba-01"})
        assert ficha == api.json()
    for racha in datos["rachas"]:
        api = client.get(f"/api/v1/rachas/{racha['temporada']}", {"estacion": "prueba-01"})
        assert racha == api.json()


def test_resumen_diario_mantiene_los_nulos(tmp_path, estacion):
    cargar_dias(estacion, date(2024, 10, 1), 2, tmedia=20, tmax=30, tmin=10)
    cargar_dias(estacion, date(2024, 10, 3), 1, motivo_nulo="Celda vacía en el Excel")
    cargar_dias(estacion, date(2024, 10, 4), 1, tmedia=21, tmax=31, tmin=11)

    _, datos = exportar(tmp_path)

    (resumen,) = datos["resumen_diario"]
    assert (resumen["desde"], resumen["hasta"]) == ("2024-10-01", "2024-10-04")
    vacio = resumen["dias"][2]
    assert vacio["tmax"] is None and vacio["motivo_nulo"] == "Celda vacía en el Excel"


def test_estaciones_sin_datos_no_generan_bloques(tmp_path):
    # las migraciones ya dejan cargadas las estaciones reales, sin mediciones
    _, datos = exportar(tmp_path)

    assert datos["estaciones"]
    assert datos["resumen_diario"] == datos["ficha_temporada"] == datos["rachas"] == []


def test_no_reemplaza_el_archivo_sin_sobrescribir(tmp_path):
    salida, _ = exportar(tmp_path)

    with pytest.raises(CommandError):
        call_command("exportar_json", "--salida", str(salida))
    call_command("exportar_json", "--salida", str(salida), "--sobrescribir")


def test_estacion_referencia_conserva_resumen_pero_no_publica_indices(client, tmp_path):
    referencia = Estacion.objects.create(
        nombre="Estación externa",
        codigo="externa-test",
        tipo=Estacion.Tipo.REFERENCIA,
    )

    cargar_dias(
        referencia,
        date(2024, 10, 1),
        3,
        tmedia=20,
        tmax=30,
        tmin=10,
    )

    # Simulamos un índice antiguo que quedó almacenado.
    IndiceClimatico.objects.create(
        estacion=referencia,
        temporada="2024-2025",
        indice="Winkler",
        valor=1500,
        confiable=True,
    )

    _, datos = exportar(tmp_path)

    # La estación aparece correctamente identificada.
    estacion_publicada = next(e for e in datos["estaciones"] if e["id"] == referencia.codigo)
    assert estacion_publicada["tipo"] == "referencia"

    # Conserva sus resúmenes diarios.
    resumen = next(r for r in datos["resumen_diario"] if r["estacion_id"] == referencia.codigo)
    assert len(resumen["dias"]) == 3

    # No expone índices ni clasificación.
    ficha = next(f for f in datos["ficha_temporada"] if f["estacion_id"] == referencia.codigo)
    assert ficha["indices"] is None
    assert ficha["clasificacion"] is None

    # La API individual respeta la misma regla.
    respuesta = client.get(
        "/api/v1/temporadas/2024-2025",
        {"estacion": referencia.codigo},
    )

    assert respuesta.status_code == 200
    assert respuesta.json()["indices"] is None
    assert respuesta.json()["clasificacion"] is None

    # El índice antiguo permanece almacenado, pero no se publica.
    assert IndiceClimatico.objects.filter(estacion=referencia).exists()
