"""Adaptador de índices reales del pipeline al análisis exploratorio E1C-20."""

import hashlib
import json
import math
from datetime import date

from apps.clima.models import ConfiguracionCalidad, IndiceClimatico
from apps.ml.correlaciones import (
    MIN_MUESTRA,
    REPETICIONES,
    SEMILLA,
    UMBRAL_HISTORICO_CORTO,
    analizar_objetivo,
)
from apps.ml.historico import validar_historico


def _metodologia(indice):
    if not indice.version_calculo or not isinstance(indice.parametros, dict):
        raise ValueError("metodologia_ausente")
    parametros = dict(indice.parametros)
    parametros.pop("completitud_pct", None)  # Se recalcula desde los conteos.
    for campo in ("fecha_inicio", "fecha_fin"):
        if campo in parametros:
            fecha = date.fromisoformat(parametros[campo])
            parametros[campo] = [fecha.year - int(indice.temporada[:4]), fecha.month, fecha.day]
    return json.dumps(
        {"version": indice.version_calculo, "parametros": parametros},
        sort_keys=True,
        allow_nan=False,
    )


def generar_informe(documento, estacion, cepa):
    historico = validar_historico(documento)
    if not estacion.subzona:
        raise ValueError("La estación debe tener una subzona para enlazar el histórico.")
    filas = {
        f["temporada"]: f
        for f in historico
        if f["subzona"] == estacion.subzona and f["cepa"] == cepa
    }
    if not filas:
        raise ValueError(
            "No hay registros que coincidan exactamente con subzona de la estación y cepa."
        )
    umbral = ConfiguracionCalidad.obtener_umbral()
    if not math.isfinite(umbral) or not 0 <= umbral <= 100:
        raise ValueError("El umbral de completitud configurado debe estar entre 0 y 100.")
    registros = list(
        IndiceClimatico.objects.filter(
            estacion=estacion,
            temporada__in=filas,
        ).order_by("indice", "temporada")
    )
    nombres = sorted({i.indice for i in registros})
    if not nombres:
        raise ValueError(
            "No hay índices calculados para estas temporadas y estación; ejecute el pipeline primero."
        )
    lookup = {(i.indice, i.temporada): i for i in registros}
    valores = {nombre: {} for nombre in nombres}
    exclusiones = {nombre: [] for nombre in nombres}
    procedencia = []
    for nombre in nombres:
        firmas = set()
        for temporada in sorted(filas):
            indice = lookup.get((nombre, temporada))
            motivo = None
            firma = None
            if indice is None:
                motivo = "indice_ausente"
            else:
                procedencia.append(
                    {
                        "indice": nombre,
                        "temporada": temporada,
                        "valor": indice.valor,
                        "confiable": indice.confiable,
                        "dias_con_dato": indice.dias_con_dato,
                        "dias_esperados": indice.dias_esperados,
                        "version_calculo": indice.version_calculo,
                        "parametros": indice.parametros,
                        "calculado_en": indice.calculado_en.isoformat(),
                    }
                )
                if not math.isfinite(indice.valor):
                    motivo = "valor_no_finito"
                    procedencia[-1]["valor"] = None
                elif not indice.confiable:
                    motivo = "indice_no_confiable"
                elif (
                    indice.dias_esperados <= 0
                    or indice.dias_con_dato <= 0
                    or indice.dias_con_dato > indice.dias_esperados
                ):
                    motivo = "conteos_invalidos"
                elif 100 * indice.dias_con_dato / indice.dias_esperados < umbral:
                    motivo = "completitud_insuficiente"
                else:
                    try:
                        firma = _metodologia(indice)
                    except (ValueError, TypeError):
                        motivo = "metodologia_ausente_o_invalida"
            if motivo:
                exclusiones[nombre].append({"temporada": temporada, "motivo": motivo})
            else:
                firmas.add(firma)
                valores[nombre][temporada] = indice.valor
        if len(firmas) > 1:
            exclusiones[nombre].extend(
                {"temporada": t, "motivo": "metodologias_incompatibles"} for t in valores[nombre]
            )
            valores[nombre] = {}
    objetivos = {
        "fecha_cosecha": {
            t: f["dia_cosecha"] for t, f in filas.items() if f["dia_cosecha"] is not None
        },
        "calidad": {
            t: f["calidad_numerica"] for t, f in filas.items() if f["calidad_numerica"] is not None
        },
    }
    return {
        "version": "e1c20-v1",
        "cohorte": {"estacion": estacion.codigo, "subzona": estacion.subzona, "cepa": cepa},
        "metodo": {
            "correlacion": "spearman",
            "empates": "rangos_medios",
            "p_valor": "permutacion_bilateral_por_valor_absoluto",
            "exacta_hasta_n": 8,
            "repeticiones_monte_carlo": REPETICIONES,
            "semilla": SEMILLA,
            "min_muestra": MIN_MUESTRA,
            "umbral_historico_corto": UMBRAL_HISTORICO_CORTO,
            "ranking": "abs(rho), mismas temporadas por objetivo; empates comparten posición",
            "ajuste_p_ranking": "Holm por objetivo; no ajusta entre objetivos ni múltiples ejecuciones",
            "unidad_fecha": "días transcurridos desde el 1 de julio de inicio de temporada (día 0)",
            "umbral_completitud_pct": umbral,
        },
        "escala_calidad": documento["escala_calidad"],
        "historico_sha256": hashlib.sha256(
            json.dumps(documento, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
        ).hexdigest(),
        "n_registros_entrada": len(historico),
        "n_registros_cohorte": len(filas),
        "n_registros_otras_cohortes": len(historico) - len(filas),
        "datos_analizados": [filas[t] for t in sorted(filas)],
        "indices_origen": procedencia,
        "resultados": {
            nombre: analizar_objetivo(datos, valores, exclusiones)
            for nombre, datos in objetivos.items()
        },
    }
