"""Resultados reales, adaptados al contrato del frontend."""

from datetime import date
from unicodedata import normalize

from django.conf import settings
from django.db.models import Count, Max, Min, Q
from django.utils import timezone
from rest_framework.exceptions import NotFound

from apps.clima.calidad import (
    MOTIVO_EXCLUIDO,
    construir_calidad_dato,
    resolucion_desde_origenes,
    resolucion_estacion,
)
from apps.clima.clasificacion import clasificar_temporada
from apps.clima.dias_criticos import obtener_dias_criticos
from apps.clima.lluvia import comparar_lluvia_invernal, lluvia_invernal
from apps.clima.lluvia_fuera_invierno import lluvia_fuera_invierno
from apps.clima.metricas import calidad_metrica, valor_metrica, version_calculo
from apps.clima.models import ConfiguracionCalidad, Estacion, IndiceClimatico, ResumenDiario
from apps.clima.rachas import identificar_rachas
from apps.clima.temporadas import (
    rango_dias_calor,
    rango_huglin,
    rango_invernal,
    rango_temporada,
    rango_winkler,
)

RANGOS_INDICE = {"Winkler": rango_winkler, "Huglin": rango_huglin}
HAY_DATO = (
    Q(tmax__isnull=False)
    | Q(tmin__isnull=False)
    | Q(tmedia__isnull=False)
    | Q(precipitacion__isnull=False)
    | Q(humedad_media__isnull=False)
    | Q(radiacion_maxima__isnull=False)
    | Q(viento_maximo__isnull=False)
)

HAY_INFORMACION = HAY_DATO | Q(motivo_nulo__contains=MOTIVO_EXCLUIDO)


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
        if ResumenDiario.objects.filter(
            estacion=estacion,
            fecha__range=(inicio, fin),
            motivo_nulo__contains=MOTIVO_EXCLUIDO,
        ).exists():
            resultado["motivo_nulo"] = (
                "Sin temperaturas suficientes para calcular el índice; "
                "hay variables excluidas por el administrador."
            )
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
    if c is None:
        return None
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

    es_referencia = estacion.tipo == Estacion.Tipo.REFERENCIA

    indices = (
        {}
        if es_referencia
        else {
            i.indice: i
            for i in IndiceClimatico.objects.filter(
                estacion=estacion,
                temporada=temporada,
                indice__in=("Winkler", "Huglin"),
            )
        }
    )
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
    # Las rachas usan la temporada; la métrica de días usa su ventana configurada.
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
        "indices": None
        if es_referencia
        else {
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


# Funciones del contrato JSON


def resumen_diario(estacion: Estacion, desde: str, hasta: str) -> dict:
    dias = ResumenDiario.objects.filter(estacion=estacion, fecha__range=[desde, hasta]).order_by(
        "fecha"
    )
    data = {"estacion_id": estacion.codigo, "desde": desde, "hasta": hasta, "dias": []}

    for d in dias:
        dia_dict = {
            "fecha": d.fecha.strftime("%Y-%m-%d"),
            "tmax": d.tmax,
            "tmin": d.tmin,
            "tmedia": d.tmedia,
            "amplitud": d.amplitud_termica,
            "precipitacion": d.precipitacion,
            "humedad_media": d.humedad_media,
            "radiacion_maxima": d.radiacion_maxima,
            "viento_maximo": d.viento_maximo,
            "corregido_a_mano": d.corregido_a_mano,
        }
        if d.motivo_nulo:
            dia_dict["motivo_nulo"] = d.motivo_nulo
        data["dias"].append(dia_dict)
    return data


def completitud_por_temporada(estacion: Estacion | None = None) -> list[dict]:
    qs = ResumenDiario.objects.filter(estacion__activa=True)

    if estacion is not None:
        qs = qs.filter(estacion=estacion)

    umbral = ConfiguracionCalidad.obtener_umbral()
    hoy = timezone.localdate()

    filas = (
        qs.values("estacion__codigo", "temporada")
        .annotate(
            n_tmax=Count("tmax"),
            n_tmin=Count("tmin"),
            n_tmedia=Count("tmedia"),
            n_precipitacion=Count("precipitacion"),
            n_humedad_media=Count("humedad_media"),
            n_radiacion_maxima=Count("radiacion_maxima"),
            n_viento_maximo=Count("viento_maximo"),
        )
        .order_by("estacion__codigo", "temporada")
    )

    resultado = []
    for f in filas:
        inicio, fin = rango_temporada(f["temporada"])
        fin = min(fin, hoy)
        total = max((fin - inicio).days + 1, 1)

        def pct(n, total=total):
            return round(min(n / total * 100, 100), 1)

        variables = {
            "tmax": pct(f["n_tmax"]),
            "tmin": pct(f["n_tmin"]),
            "tmedia": pct(f["n_tmedia"]),
            "precipitacion": pct(f["n_precipitacion"]),
            "humedad_media": pct(f["n_humedad_media"]),
            "radiacion_maxima": pct(f["n_radiacion_maxima"]),
            "viento_maximo": pct(f["n_viento_maximo"]),
        }

        item = {
            "estacion_id": f["estacion__codigo"],
            "temporada": f["temporada"],
            "variables": variables,
            "confiable": variables["tmax"] >= umbral and variables["tmin"] >= umbral,
        }

        if variables["precipitacion"] == 0:
            item["observacion"] = "sin datos de precipitación en la temporada"

        resultado.append(item)

    return resultado


def temporadas() -> list[str]:
    return list(
        ResumenDiario.objects.filter(
            HAY_INFORMACION,
            estacion__activa=True,
        )
        .order_by("temporada")
        .values_list("temporada", flat=True)
        .distinct()
    )


def estaciones(incluir_inactivas: bool = False) -> list[dict]:
    umbral = ConfiguracionCalidad.obtener_umbral()
    resultado = []

    qs_estaciones = Estacion.objects.order_by("nombre")

    if not incluir_inactivas:
        qs_estaciones = qs_estaciones.filter(activa=True)

    for est in qs_estaciones:
        qs = ResumenDiario.objects.filter(estacion=est)

        agg = qs.filter(HAY_INFORMACION).aggregate(
            inicio=Min("fecha"),
            fin=Max("fecha"),
            n_completos=Count(
                "id",
                filter=Q(tmax__isnull=False, tmin__isnull=False),
            ),
            n_tmax=Count("tmax"),
            n_tmin=Count("tmin"),
            n_tmedia=Count("tmedia"),
            n_precipitacion=Count("precipitacion"),
            n_humedad_media=Count("humedad_media"),
            n_radiacion_maxima=Count("radiacion_maxima"),
            n_viento_maximo=Count("viento_maximo"),
        )

        variables = [
            nombre
            for nombre, n in [
                ("tmax", agg["n_tmax"]),
                ("tmin", agg["n_tmin"]),
                ("tmedia", agg["n_tmedia"]),
                ("precipitacion", agg["n_precipitacion"]),
                ("humedad_media", agg["n_humedad_media"]),
                ("radiacion_maxima", agg["n_radiacion_maxima"]),
                ("viento_maximo", agg["n_viento_maximo"]),
            ]
            if n > 0
        ]

        completitud = None
        if agg["inicio"]:
            dias_rango = (agg["fin"] - agg["inicio"]).days + 1
            completitud = round(agg["n_completos"] / dias_rango * 100, 1)

        origenes = qs.order_by().values_list("origen", flat=True).distinct()
        resolucion = resolucion_desde_origenes(origenes)

        n_temporadas = qs.filter(HAY_INFORMACION).order_by().values("temporada").distinct().count()

        resultado.append(
            {
                "id": est.codigo,
                "nombre": est.nombre,
                "subzona": est.subzona,
                "propietario": est.propietario,
                "latitud": est.latitud,
                "longitud": est.longitud,
                "variables": variables,
                "fecha_inicio": (agg["inicio"].isoformat() if agg["inicio"] else None),
                "fecha_fin": (agg["fin"].isoformat() if agg["fin"] else None),
                "temporadas_disponibles": n_temporadas,
                "calidad_dato": {
                    "completitud_pct": completitud,
                    "confiable": (completitud is not None and completitud >= umbral),
                    "umbral_completitud_pct": umbral,
                    "resolucion_origen": resolucion,
                    "version_calculo": None,
                },
                "tipo": est.tipo,
            }
        )

    return resultado
