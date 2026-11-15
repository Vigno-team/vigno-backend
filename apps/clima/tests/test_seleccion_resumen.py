from datetime import datetime

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.clima import correcciones
from apps.clima.lluvia import eventos_lluvia
from apps.clima.management.commands.exportar_json import exportar
from apps.clima.models import Estacion, IndiceClimatico, MedicionHoraria, ResumenDiario
from apps.clima.services import MOTIVO_EXCLUIDO
from apps.ingesta.models import RegistroCarga

pytestmark = pytest.mark.django_db


@pytest.fixture
def estacion():
    return Estacion.objects.create(nombre="Selección", codigo="seleccion", latitud=-35)


def medir(estacion, variable, valor, hora=12, frecuencia="D", **campos):
    return MedicionHoraria.objects.create(
        estacion=estacion,
        timestamp=timezone.make_aware(datetime(2025, 1, 15, hora)),
        variable=variable,
        frecuencia=frecuencia,
        valor=valor,
        **campos,
    )


def recalcular():
    call_command("generar_resumenes", verbosity=0)
    call_command("calcular_indices", verbosity=0)


def test_humedad_sola_llega_al_dashboard_y_no_inventa_indices(estacion):
    medir(estacion, "humedad_media", 72)
    recalcular()
    datos = exportar()
    serie = next(d for d in datos["resumen_diario"] if d["estacion_id"] == estacion.codigo)
    assert serie["dias"][0]["humedad_media"] == 72
    assert serie["dias"][0]["radiacion_maxima"] is None
    assert serie["dias"][0]["viento_maximo"] is None
    ficha = next(f for f in datos["ficha_temporada"] if f["estacion_id"] == estacion.codigo)
    for indice in ficha["indices"].values():
        assert indice["valor"] is None
        assert indice["motivo_nulo"]
    catalogo = next(e for e in datos["estaciones"] if e["id"] == estacion.codigo)
    assert catalogo["variables"] == ["humedad_media"]


def test_excluir_todo_invalida_y_reincluir_recupera_indice_sin_borrar_original(estacion):
    medir(estacion, "temperatura_media", 20)
    recalcular()
    anterior = IndiceClimatico.objects.get(estacion=estacion, indice="Winkler").valor
    MedicionHoraria.objects.filter(estacion=estacion).update(excluido=True)
    recalcular()
    assert not IndiceClimatico.objects.filter(estacion=estacion).exists()
    resumen = ResumenDiario.objects.get(estacion=estacion)
    assert resumen.tmedia is None
    assert resumen.motivo_nulo == MOTIVO_EXCLUIDO
    ficha = next(f for f in exportar()["ficha_temporada"] if f["estacion_id"] == estacion.codigo)
    assert ficha["indices"]["winkler"]["valor"] is None
    assert "excluidas" in ficha["indices"]["winkler"]["motivo_nulo"]
    original = MedicionHoraria.objects.get(estacion=estacion)
    assert original.valor == 20
    original.excluido = False
    original.save(update_fields=["excluido"])
    recalcular()
    assert IndiceClimatico.objects.get(estacion=estacion, indice="Winkler").valor == anterior


def test_horarios_agregan_sensores_validos_sin_valores_excluidos(estacion):
    for hora, humedad, radiacion, viento in [(12, 40, 100, 5), (13, 60, 200, 7), (14, 99, 999, 99)]:
        for variable, valor in (
            ("humedad_media", humedad),
            ("radiacion_maxima", radiacion),
            ("viento_maximo", viento),
        ):
            medir(estacion, variable, valor, hora, "H", excluido=hora == 14)
    call_command("generar_resumenes")
    resumen = ResumenDiario.objects.get(estacion=estacion)
    assert (resumen.humedad_media, resumen.radiacion_maxima, resumen.viento_maximo) == (50, 200, 7)
    assert resumen.tmax is None and resumen.tmin is None and resumen.tmedia is None


def test_maxima_excluida_no_reaparece_desde_media_horaria(estacion):
    medir(estacion, "temperatura_maxima", 30, frecuencia="H", excluido=True)
    medir(estacion, "temperatura_media", 20, frecuencia="H")
    recalcular()
    resumen = ResumenDiario.objects.get(estacion=estacion)
    assert resumen.tmax is None
    assert resumen.tmedia == 20
    assert IndiceClimatico.objects.filter(estacion=estacion, indice="Winkler").exists()
    assert not IndiceClimatico.objects.filter(estacion=estacion, indice="Huglin").exists()


def test_maxima_y_minima_horarias_siguen_utiles_sin_media(estacion):
    medir(estacion, "temperatura_maxima", 30, frecuencia="H")
    medir(estacion, "temperatura_minima", 10, frecuencia="H")
    medir(estacion, "temperatura_media", 22, frecuencia="H", excluido=True)
    recalcular()
    resumen = ResumenDiario.objects.get(estacion=estacion)
    assert (resumen.tmax, resumen.tmin, resumen.tmedia) == (30, 10, None)
    assert IndiceClimatico.objects.get(estacion=estacion, indice="Winkler").valor == 10
    assert IndiceClimatico.objects.get(estacion=estacion, indice="Huglin").valor == 15


def test_fuera_de_rango_excluido_no_invalida_horas_elegidas(estacion):
    medir(estacion, "temperatura_media", 20, hora=12, frecuencia="H")
    medir(
        estacion,
        "temperatura_media",
        80,
        hora=13,
        frecuencia="H",
        fuera_de_rango=True,
        excluido=True,
    )
    medir(estacion, "precipitacion", 5, hora=12, frecuencia="H")
    medir(estacion, "precipitacion", 99, hora=13, frecuencia="H", excluido=True)
    call_command("generar_resumenes")
    resumen = ResumenDiario.objects.get(estacion=estacion)
    assert resumen.tmedia == 20
    assert resumen.precipitacion == 5
    eventos = eventos_lluvia(estacion, "2025-01-15", "2025-01-15")
    assert sum(evento["total_mm"] for evento in eventos["eventos"]) == 5


@pytest.mark.parametrize("excluir_al_revertir", [False, True])
def test_correccion_manual_es_visible_y_reversion_respeta_seleccion_actual(
    estacion, monkeypatch, excluir_al_revertir
):
    monkeypatch.setattr(correcciones, "_reintegrar", lambda: {"ok": True})
    registro = RegistroCarga.objects.create(
        archivo="temperaturas.xlsx",
        estacion=estacion.nombre,
        variables_procesadas=["temperatura_media"],
        variables_excluidas=["temperatura_media"],
    )
    dato = medir(estacion, "temperatura_media", 20, excluido=True, carga=registro)
    correccion, _ = correcciones.crear_correccion(
        {
            "estacion": estacion,
            "timestamp": dato.timestamp,
            "variable": dato.variable,
            "frecuencia": "D",
            "valor_nuevo": 21,
            "motivo": "Planilla manual",
            "autor": "Administración",
        }
    )
    dato.refresh_from_db()
    assert dato.origen == "manual" and not dato.excluido
    call_command("generar_resumenes")
    assert ResumenDiario.objects.get(estacion=estacion).tmedia == 21
    registro.variables_excluidas = ["temperatura_media"] if excluir_al_revertir else []
    registro.save(update_fields=["variables_excluidas"])
    correcciones.revertir_correccion(correccion.pk, {"autor": "Admin", "motivo": "Revisión"})
    dato.refresh_from_db()
    assert dato.valor == 20 and dato.origen == "excel"
    assert dato.excluido is excluir_al_revertir


def test_reversion_de_correccion_legacy_respeta_exclusion_de_carga(estacion, monkeypatch):
    from apps.ingesta.seleccion import cambiar_seleccion

    monkeypatch.setattr(correcciones, "_reintegrar", lambda: {"ok": True})
    registro = RegistroCarga.objects.create(
        archivo="temperaturas.xlsx",
        estacion=estacion.nombre,
        fecha_desde="2025-01-15",
        fecha_hasta="2025-01-15",
        variables_procesadas=["temperatura_media"],
    )
    dato = medir(estacion, "temperatura_media", 20)
    correccion, _ = correcciones.crear_correccion(
        {
            "estacion": estacion,
            "timestamp": dato.timestamp,
            "variable": dato.variable,
            "frecuencia": "D",
            "valor_nuevo": 21,
            "motivo": "Planilla manual",
            "autor": "Admin",
        }
    )
    cambiar_seleccion(registro.pk, {"variables_excluidas": ["temperatura_media"]})
    correcciones.revertir_correccion(correccion.pk, {"autor": "Admin", "motivo": "Revisión"})
    dato.refresh_from_db()
    assert dato.excluido is True
    assert dato.carga_id == registro.pk


def test_humedad_horaria_no_oculta_temperatura_diaria(estacion):
    medir(estacion, "temperatura_media", 20)
    medir(estacion, "humedad_media", 65, frecuencia="H")
    recalcular()
    resumen = ResumenDiario.objects.get(estacion=estacion)
    assert resumen.tmedia == 20
    assert resumen.humedad_media == 65
    assert IndiceClimatico.objects.get(estacion=estacion, indice="Winkler").valor == 10


def test_reversion_legacy_ambigua_no_reactiva_dato_excluido(estacion, monkeypatch):
    monkeypatch.setattr(correcciones, "_reintegrar", lambda: {"ok": True})
    for nombre, excluidas in [("original.xlsx", ["temperatura_media"]), ("otro.xlsx", [])]:
        RegistroCarga.objects.create(
            archivo=nombre,
            estacion=estacion.nombre,
            fecha_desde="2025-01-15",
            fecha_hasta="2025-01-15",
            variables_procesadas=["temperatura_media"],
            variables_excluidas=excluidas,
        )
    dato = medir(estacion, "temperatura_media", 20)
    correccion, _ = correcciones.crear_correccion(
        {
            "estacion": estacion,
            "timestamp": dato.timestamp,
            "variable": dato.variable,
            "frecuencia": "D",
            "valor_nuevo": 21,
            "motivo": "Planilla manual",
            "autor": "Admin",
        }
    )
    with pytest.raises(correcciones.ConflictoCorreccion, match="varias cargas antiguas"):
        correcciones.revertir_correccion(correccion.pk, {"autor": "Admin", "motivo": "Revisión"})
    dato.refresh_from_db()
    correccion.refresh_from_db()
    assert dato.origen == "manual" and dato.valor == 21
    assert correccion.estado == "vigente"


def test_datos_mixtos_priorizan_horarios_por_variable_sin_ocultar_sensores(estacion):
    medir(estacion, "temperatura_media", 20)
    medir(estacion, "humedad_media", 65)
    medir(estacion, "precipitacion", 3)
    medir(estacion, "temperatura_media", 22, frecuencia="H")
    medir(estacion, "viento_maximo", 4, frecuencia="H")
    recalcular()
    resumen = ResumenDiario.objects.get(estacion=estacion)
    assert resumen.tmedia == 22
    assert resumen.humedad_media == 65
    assert resumen.precipitacion == 3
    assert resumen.viento_maximo == 4
    assert resumen.origen == "H"


def test_dato_diario_no_oculta_error_de_rango_horario(estacion):
    medir(estacion, "temperatura_media", 20)
    medir(estacion, "temperatura_maxima", 30)
    medir(estacion, "temperatura_minima", 10)
    medir(estacion, "temperatura_media", 80, frecuencia="H", fuera_de_rango=True)
    recalcular()
    resumen = ResumenDiario.objects.get(estacion=estacion)
    assert resumen.tmax is None and resumen.tmedia is None and resumen.tmin is None
    assert resumen.confiable is False
    assert not IndiceClimatico.objects.filter(estacion=estacion).exists()
