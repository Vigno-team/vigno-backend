"""Resultados reales de E1C-17, adaptados al contrato del frontend."""

from datetime import date
from unicodedata import normalize

from django.conf import settings
from django.db.models import Count
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.clima.calidad import construir_calidad_dato, resolucion_estacion
from apps.clima.clasificacion import clasificar_temporada
from apps.clima.dias_criticos import obtener_dias_criticos
from apps.clima.lluvia import comparar_lluvia_invernal, lluvia_invernal
from apps.clima.lluvia_fuera_invierno import lluvia_fuera_invierno
from apps.clima.metricas import calidad_metrica, valor_metrica, version_calculo
from apps.clima.models import ConfiguracionCalidad, IndiceClimatico, ResumenDiario
from apps.clima.rachas import identificar_rachas
from apps.clima.temporadas import (
    rango_dias_calor,
    rango_huglin,
    rango_invernal,
    rango_temporada,
    rango_winkler,
)

RANGOS_INDICE = {"Winkler": rango_winkler, "Huglin": rango_huglin}


def _periodo_indice(indice, temporada, tipo):
    inicio, fin = RANGOS_INDICE[tipo](temporada)
    if indice:
        parametros = indice.parametros
        inicio = date.fromisoformat(parametros.get("fecha_inicio", inicio.isoformat()))
        fin = date.fromisoformat(parametros.get("fecha_fin", fin.isoformat()))
    return inicio, fin


def _bloque_indice(estacion, temporada, tipo, indice, umbral):
    inicio, fin = _periodo_indice(indice, temporada, tipo)
    campo = "region" if tipo == "Winkler" else "clasificacion"
    calidad = calidad_metrica(
        indice.dias_con_dato if indice else 0,
        indice.dias_esperados if indice else 0,
        umbral,
        habilitada=indice is not None and indice.confiable,
    )
    completitud, confiable = calidad["completitud_pct"], calidad["confiable"]
    etiqueta = None
    if confiable and indice.clasificacion:
        if tipo == "Winkler":
            regiones = {f"Región {r}": r for r in ("I", "II", "III", "IV", "V")}
            etiqueta = regiones.get(indice.clasificacion)
        else:
            etiqueta = normalize("NFKD", indice.clasificacion).encode("ascii", "ignore").decode()
            etiqueta = etiqueta.lower()
    resultado = {
        "valor": indice.valor if indice else None,
        campo: etiqueta,
        "calidad_dato": construir_calidad_dato(
            completitud,
            confiable,
            umbral,
            resolucion_estacion(estacion, inicio, fin),
            indice.version_calculo if indice else None,
        ),
    }
    if indice is None:
        resultado["motivo_nulo"] = "No hay un resultado calculado para este índice y temporada."
    return resultado


def comprobar_temporada(estacion, temporada):
    """404 si no existe información para la estación en esa temporada."""
    inicio, fin = rango_invernal(temporada)
    existe = (
        ResumenDiario.objects.filter(estacion=estacion, temporada=temporada).exists()
        or IndiceClimatico.objects.filter(estacion=estacion, temporada=temporada).exists()
        or ResumenDiario.objects.filter(
            estacion=estacion, fecha__range=(inicio, fin), precipitacion__isnull=False
        ).exists()
    )
    if not existe:
        raise NotFound("No hay datos para esta estación y temporada.")


def resultados_rachas(estacion, temporada):
    comprobar_temporada(estacion, temporada)
    umbral = ConfiguracionCalidad.obtener_umbral()
    umbral_c = settings.UMBRAL_CALOR_C
    minimo_dias = settings.MINIMO_DIAS_INCIDENCIA
    inicio, fin = rango_temporada(temporada)
    fin_efectivo = min(fin, timezone.localdate())
    dias_esperados = max((fin_efectivo - inicio).days + 1, 0)
    dias_con_dato = ResumenDiario.objects.filter(
        estacion=estacion, temporada=temporada, fecha__range=(inicio, fin_efectivo)
    ).aggregate(n=Count("tmax"))["n"]
    calidad = calidad_metrica(dias_con_dato, dias_esperados, umbral)
    completitud, confiable = calidad["completitud_pct"], calidad["confiable"]
    rachas = identificar_rachas(estacion, temporada, umbral_temp=umbral_c, min_dias=minimo_dias)
    # Publicamos los campos acordados, conservando la advertencia sobre huecos.
    version = f"rachas-v1_{umbral_c:g}c_min{minimo_dias}_temporada"
    return {
        "temporada": temporada,
        "estacion_id": estacion.codigo,
        "umbral_c": umbral_c,
        "minimo_dias_incidencia": minimo_dias,
        "rachas": rachas,
        "calidad_dato": construir_calidad_dato(
            completitud, confiable, umbral, resolucion_estacion(estacion, inicio, fin), version
        ),
    }


def _clasificacion(estacion, temporada):
    """Cálida/fría y lluviosa/seca. None solo si no se puede clasificar ningún eje."""
    c = clasificar_temporada(estacion, temporada)
    if c["termica"] is None and c["hidrica"] is None:
        return None
    bloque = {
        "termica": c["termica"],
        "hidrica": c["hidrica"],
        "criterio": c["criterio"],
        "en_curso": c["en_curso"],
        "parcial_hasta": c["parcial_hasta"],
    }
    faltan = [
        f"{eje}: {c['detalle'][eje].get('observacion', 'sin datos suficientes')}"
        for eje in ("termica", "hidrica")
        if c[eje] is None
    ]
    if faltan:
        bloque["motivo_nulo"] = "; ".join(faltan)
    return bloque


def ficha_temporada(estacion, temporada):
    comprobar_temporada(estacion, temporada)
    umbral = ConfiguracionCalidad.obtener_umbral()
    indices = {
        i.indice: i
        for i in IndiceClimatico.objects.filter(
            estacion=estacion, temporada=temporada, indice__in=("Winkler", "Huglin")
        )
    }
    inicio, fin = _periodo_indice(indices.get("Winkler"), temporada, "Winkler")
    lluvia = lluvia_invernal(estacion, temporada)
    historico = comparar_lluvia_invernal(estacion, temporadas=[temporada])
    comparacion = next(iter(historico["temporadas"]), {})
    ini_invierno, fin_invierno = rango_invernal(temporada)
    bloque_lluvia = {
        "acumulado_mm": lluvia["acumulado_mm"],
        "promedio_historico_mm": historico["promedio_historico_mm"],
        "diferencia_pct": comparacion.get("diferencia_pct"),
        "calidad_dato": construir_calidad_dato(
            lluvia["completitud_pct"],
            lluvia["dias_con_dato"] > 0 and lluvia["confiable"],
            umbral,
            resolucion_estacion(estacion, ini_invierno, fin_invierno),
            version_calculo("lluvia_invernal", temporada),
        ),
    }
    if lluvia["acumulado_mm"] is None:
        bloque_lluvia["motivo_nulo"] = "Sin datos de precipitación en el período invernal."
    lluvia_exterior = lluvia_fuera_invierno(estacion, temporada)
    rachas = resultados_rachas(estacion, temporada)
    calor_metrica = valor_metrica(
        estacion, "dias_sobre_umbral", temporada, timezone.localdate(), umbral
    )
    # Las rachas conservan su ventana anual; la métrica de días usa octubre-abril.
    hay_temperatura = ResumenDiario.objects.filter(
        estacion=estacion, temporada=temporada, tmax__isnull=False
    ).exists()
    inicio_calor, fin_calor = rango_dias_calor(temporada)
    calor = {
        "dias_sobre_umbral": calor_metrica["valor"],
        "umbral_c": rachas["umbral_c"],
        "rachas_con_incidencia": sum(r["con_incidencia"] for r in rachas["rachas"])
        if hay_temperatura
        else None,
        "racha_maxima_dias": max((r["dias"] for r in rachas["rachas"]), default=0)
        if hay_temperatura
        else None,
        "calidad_dato": construir_calidad_dato(
            calor_metrica["completitud_pct"],
            calor_metrica["confiable"],
            umbral,
            resolucion_estacion(estacion, inicio_calor, fin_calor),
            version_calculo("dias_sobre_umbral", temporada),
        ),
    }
    if calor_metrica["valor"] is None:
        calor["motivo_nulo"] = "Sin temperaturas máximas en la ventana de días de calor."
    return {
        "temporada": temporada,
        "estacion_id": estacion.codigo,
        "subzona": estacion.subzona,
        "periodo": {"inicio": inicio.isoformat(), "fin": fin.isoformat()},
        "indices": {
            tipo.lower(): _bloque_indice(estacion, temporada, tipo, indices.get(tipo), umbral)
            for tipo in ("Winkler", "Huglin")
        },
        "lluvia_invernal": bloque_lluvia,
        "lluvia_fuera_invierno": lluvia_exterior,
        "calor": calor,
        "clasificacion": _clasificacion(estacion, temporada),
        "dias_criticos": obtener_dias_criticos(estacion, temporada, limite=10),
        "dias_corregidos_a_mano": ResumenDiario.objects.filter(
            estacion=estacion, temporada=temporada, corregido_a_mano=True
        ).count(),
    }
