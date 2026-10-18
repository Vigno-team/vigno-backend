import importlib.util
import io
import json
import os
import re
from datetime import date, datetime
from itertools import islice
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.core.management import call_command

from apps.clima.metricas import clasificar_huglin, clasificar_winkler
from apps.clima.models import Estacion, IndiceClimatico, MedicionHoraria, ResumenDiario
from apps.clima.temporadas import temporada_de

pytestmark = pytest.mark.django_db

DIR_SINTETICO = Path(settings.BASE_DIR) / "data" / "synthetic"
REFERENCIA = Path(__file__).parent / "referencia" / "json_completo.json"
VARIABLE_ENTORNO = "REGENERAR_REFERENCIA"
TZ = ZoneInfo("America/Santiago")
MAX_DIFERENCIAS = 25

# Ventanas escritas a mano.
# Código que vigila si un refactor corre una ventana, estos tests lo detectan.
VENTANAS = {
    "Winkler": ((10, 1), (4, 30)),  # 1 oct - 30 abr
    "Huglin": ((10, 1), (3, 31)),  # 1 oct - 31 mar
    "Verano": ((10, 1), (4, 30)),  # completitud de los días sobre 35 °C
}


def _ventana(temporada: str, nombre: str) -> tuple[date, date]:
    inicio = int(temporada[:4])
    (mes_ini, dia_ini), (mes_fin, dia_fin) = VENTANAS[nombre]
    return date(inicio, mes_ini, dia_ini), date(inicio + 1, mes_fin, dia_fin)


def _importar(nombre: str):
    """Carga un script de data/synthetic/ (esa carpeta no es un paquete de Python)."""
    spec = importlib.util.spec_from_file_location(
        f"_sintetico_{nombre}", DIR_SINTETICO / f"{nombre}.py"
    )
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


generador = _importar("generar_datos")
comparador = _importar("comparar_json")


# Preparación


@pytest.fixture
def estaciones(settings):
    # Los umbrales se fijan aquí para que la referencia no dependa del .env de cada máquina.
    settings.UMBRAL_CALOR_C = 35.0
    settings.MINIMO_DIAS_INCIDENCIA = 5
    # Las migraciones dejan cargadas las estaciones reales (sin mediciones): se sacan para que la referencia dependa solo de los datos sintéticos.
    Estacion.objects.all().delete()
    return {
        e["codigo"]: Estacion.objects.create(
            nombre=e["nombre"],
            codigo=e["codigo"],
            subzona=e["subzona"],
            propietario=e["propietario"],
            latitud=e["latitud"],
        )
        for e in generador.ESTACIONES
    }


@pytest.fixture
def mediciones(estaciones):
    """Los datos sintéticos como MedicionHoraria diaria, igual que los deja ingestar_excel."""
    filas = []
    for r in generador.generar():
        f = r["fecha"]
        # ingestar_excel guarda los datos diarios a las 12:00 de Chile.
        timestamp = datetime(f.year, f.month, f.day, 12, tzinfo=TZ)
        for variable in generador.VARIABLES:
            valor = r[variable]
            filas.append(
                MedicionHoraria(
                    estacion=estaciones[r["estacion"]],
                    timestamp=timestamp,
                    variable=variable,
                    frecuencia="D",
                    valor=valor,
                    motivo_nulo=generador.MOTIVO_NULO if valor is None else None,
                    temporada=f.year,
                )
            )
    MedicionHoraria.objects.bulk_create(filas, batch_size=1000)


def correr(comando, *args):
    call_command(comando, *args, stdout=io.StringIO())


@pytest.fixture
def json_exportado(tmp_path, mediciones):
    correr("generar_resumenes")
    correr("calcular_indices")
    salida = tmp_path / "exportado.json"
    correr("exportar_json", "--salida", str(salida))
    return comparador.cargar(salida)


# Referencia


def _serializar(datos: dict) -> str:
    texto = json.dumps(datos, ensure_ascii=False, indent=2, allow_nan=False)
    """ Un objeto por línea para los días, rachas y días críticos: el diff en git queda legible y el archivo  
    corto. Los objetos sin llaves anidadas no tienen saltos de línea dentro de sus textos, 
    así que esto no altera ningún valor. """
    texto = re.sub(
        r'\{\s*("(?:fecha|inicio)":[^{}\[\]]*?)\s*\}',
        lambda m: "{ " + re.sub(r"\n\s*", " ", m.group(1)) + " }",
        texto,
    )
    assert json.loads(texto) == datos
    return texto + "\n"


def test_json_completo_coincide_con_la_referencia(json_exportado):
    if os.environ.get(VARIABLE_ENTORNO):
        REFERENCIA.parent.mkdir(parents=True, exist_ok=True)
        REFERENCIA.write_text(_serializar(json_exportado), encoding="utf-8", newline="\n")
        pytest.skip(
            f"Referencia regenerada en {REFERENCIA}. Revisa el diff con git y vuelve a correr "
            f"el test sin {VARIABLE_ENTORNO}."
        )

    if not REFERENCIA.exists():
        pytest.fail(
            f"No existe la referencia {REFERENCIA}. Para crearla: "
            f"docker compose exec -e {VARIABLE_ENTORNO}=1 backend pytest {Path(__file__).name}"
        )

    esperado = json.loads(REFERENCIA.read_text(encoding="utf-8"))
    # Se decide solo con diferencias(): `==` de Python toma True == 1 como iguales.
    lista = list(islice(comparador.diferencias(esperado, json_exportado), MAX_DIFERENCIAS + 1))
    if not lista:
        return
    detalle = "\n".join(f"  {linea}" for linea in lista[:MAX_DIFERENCIAS])
    if len(lista) > MAX_DIFERENCIAS:
        detalle += f"\n  ... y más (se muestran las primeras {MAX_DIFERENCIAS})"
    pytest.fail(
        "El JSON exportado ya no coincide con la referencia:\n"
        f"{detalle}\n\n"
        "Si el cambio es intencional, regenera la referencia y revisa el diff en git "
        "(ver data/synthetic/README.md):\n"
        f"  docker compose exec -e {VARIABLE_ENTORNO}=1 backend pytest {Path(__file__).name}\n"
        "Si no era intencional, hay una regresión en el cambio que acabas de hacer."
    )


def test_la_referencia_incluye_los_casos_borde():
    """Evita que un cambio al generador deje la referencia sin cubrir lo importante."""
    if not REFERENCIA.exists():
        pytest.skip("La referencia aún no existe (la crea el test anterior).")
    datos = json.loads(REFERENCIA.read_text(encoding="utf-8"))
    fichas = datos["ficha_temporada"]
    rachas = [r for t in datos["rachas"] for r in t["rachas"]]
    dias = [d for est in datos["resumen_diario"] for d in est["dias"]]

    assert {e["id"] for e in datos["estaciones"]} == {e["codigo"] for e in generador.ESTACIONES}
    assert any(r["con_incidencia"] for r in rachas), "falta una racha con incidencia"
    assert any(not r["con_incidencia"] for r in rachas), "falta una racha sin incidencia"
    assert any(r["interrumpida_por_dato_faltante"] for r in rachas), "falta una racha interrumpida"
    assert any("motivo_nulo" in d for d in dias), "falta un día sin dato con su motivo"
    winkler = [f["indices"]["winkler"]["calidad_dato"]["confiable"] for f in fichas]
    huglin = [f["indices"]["huglin"]["calidad_dato"]["confiable"] for f in fichas]
    clasificaciones = [f["clasificacion"] for f in fichas]
    assert not all(winkler), "falta un Winkler no confiable"
    assert not all(huglin), "falta un Huglin no confiable"
    assert None in clasificaciones, "falta una ficha sin clasificación"
    con_clasificacion = [c for c in clasificaciones if c]
    assert any("motivo_nulo" in c for c in con_clasificacion), "falta una clasificación parcial"
    assert any(c["termica"] for c in con_clasificacion), "falta una clasificación térmica"
    lluvias = [f["lluvia_invernal"] for f in fichas]
    assert any("motivo_nulo" in x for x in lluvias), "falta una lluvia invernal sin datos"


# generar_resumenes y calcular_indices


def test_generar_resumenes_deja_un_resumen_por_dia_y_conserva_los_nulos(mediciones, estaciones):
    correr("generar_resumenes")

    assert ResumenDiario.objects.count() == len(generador.generar())
    vacio = ResumenDiario.objects.get(estacion=estaciones["sint-norte-01"], fecha=date(2024, 1, 24))
    assert vacio.tmax is None and vacio.confiable is False
    assert vacio.motivo_nulo == generador.MOTIVO_NULO
    sin_lluvia = ResumenDiario.objects.get(
        estacion=estaciones["sint-sur-01"], fecha=date(2024, 6, 10)
    )
    assert sin_lluvia.precipitacion is None and sin_lluvia.tmax is not None


def _esperado_de_los_datos_crudos() -> dict:
    """Calcula Winkler, Huglin y días sobre 35 °C directo de los datos crudos, sin tocar la BD."""
    umbral = 80.0
    esperado = {}
    for est in generador.ESTACIONES:
        filas = [r for r in generador.generar() if r["estacion"] == est["codigo"]]
        for temporada in sorted({temporada_de(r["fecha"]) for r in filas}):
            for indice, tipo in (("Winkler", "Winkler"), ("Huglin", "Huglin")):
                ini, fin = _ventana(temporada, tipo)
                aportes = []
                for r in filas:
                    if not ini <= r["fecha"] <= fin or r["temperatura_media"] is None:
                        continue
                    media = r["temperatura_media"]
                    if indice == "Winkler":
                        aportes.append(media - 10.0 if media > 10.0 else 0.0)
                    else:  # latitud <= 40 o sin latitud: k = 1,00
                        calculo = ((media - 10.0) + (r["temperatura_maxima"] - 10.0)) / 2.0
                        aportes.append(calculo if calculo > 0 else 0.0)
                esperados = (fin - ini).days + 1
                if aportes:
                    confiable = len(aportes) / esperados * 100.0 >= umbral
                    if indice == "Huglin":
                        confiable = confiable and est["latitud"] is not None
                    esperado[(est["codigo"], indice, temporada)] = (
                        round(sum(aportes), 1),
                        len(aportes),
                        esperados,
                        confiable,
                    )
            # E1C-120: conteo y completitud usan la misma ventana de octubre a abril.
            # El fixture fija UMBRAL_CALOR_C=35; la ventana queda escrita a mano como oráculo.
            ini, fin = _ventana(temporada, "Verano")
            con_dato = [
                r for r in filas if ini <= r["fecha"] <= fin and r["temperatura_maxima"] is not None
            ]
            if con_dato:
                dias_calor = sum(
                    r["temperatura_maxima"] >= 35.0
                    for r in filas
                    if ini <= r["fecha"] <= fin and r["temperatura_maxima"] is not None
                )
                esperado[(est["codigo"], "DiasSobreUmbral", temporada)] = (
                    float(dias_calor),
                    len(con_dato),
                    (fin - ini).days + 1,
                    (len(con_dato) / ((fin - ini).days + 1) * 100.0) >= umbral,
                )
    return esperado


def _indices_en_la_bd() -> dict:
    return {
        (i.estacion.codigo, i.indice, i.temporada): (
            i.valor,
            i.dias_con_dato,
            i.dias_esperados,
            i.confiable,
        )
        for i in IndiceClimatico.objects.select_related("estacion")
    }


def test_calcular_indices_coincide_con_el_calculo_independiente(mediciones):
    correr("generar_resumenes")
    correr("calcular_indices")

    bd = _indices_en_la_bd()
    esperado = _esperado_de_los_datos_crudos()
    assert bd.keys() == esperado.keys()
    for clave, (valor, *resto) in esperado.items():
        assert bd[clave][1:] == tuple(resto), clave
        """ Huglin suma aportes múltiplos de 0,05: el total puede caer justo en un x5 y el
        redondeo a 0,1 depende de cómo se sume."""
        assert bd[clave][0] == pytest.approx(valor, abs=0.1 + 1e-6), clave


def test_calcular_indices_clasifica_solo_los_indices_confiables(mediciones):
    correr("generar_resumenes")
    correr("calcular_indices")

    for i in IndiceClimatico.objects.filter(indice__in=("Winkler", "Huglin")):
        if not i.confiable:
            assert i.clasificacion == "Sin datos suficientes"
        elif i.indice == "Winkler":
            assert i.clasificacion == clasificar_winkler(i.valor)
        else:
            assert i.clasificacion == clasificar_huglin(i.valor)
    # El Huglin sin latitud nunca es confiable, aunque tenga todos los datos.
    sur = IndiceClimatico.objects.filter(estacion__codigo="sint-sur-01", indice="Huglin")
    assert sur.exists() and not sur.filter(confiable=True).exists()


def test_calcular_indices_es_idempotente(mediciones):
    correr("generar_resumenes")
    correr("calcular_indices")
    primero = _indices_en_la_bd()

    correr("calcular_indices")

    assert _indices_en_la_bd() == primero


def test_calcular_indices_con_estacion_usa_el_nombre_y_filtra(mediciones):
    correr("generar_resumenes")

    correr("calcular_indices", "--estacion", "Sintética Sur")

    codigos = set(IndiceClimatico.objects.values_list("estacion__codigo", flat=True))
    assert codigos == {"sint-sur-01"}
