from calendar import monthrange
from datetime import date

from django.conf import settings
from django.utils import timezone

from apps.clima.calidad import construir_calidad_dato, resolucion_desde_origenes
from apps.clima.metricas import calidad_metrica
from apps.clima.models import ConfiguracionCalidad, Estacion, ResumenDiario
from apps.clima.temporadas import (
    MES_INICIO_ANIO_AGRICOLA,
    MIN_TEMPORADAS_PROMEDIO,
    rango_anio_agricola,
    rango_crecimiento,
    rango_septiembre,
    rangos_etapas_crecimiento,
)


def _medir(lluvia, inicio: date, fin: date, hoy: date, umbral: float) -> dict:
    hasta = min(fin, hoy)
    esperados = max((hasta - inicio).days + 1, 0)
    valores = [
        valor for fecha, valor in lluvia.items() if inicio <= fecha <= hasta and valor is not None
    ]
    calidad = calidad_metrica(len(valores), esperados, umbral)
    completitud = calidad["completitud_pct"]
    return {
        "mm": round(sum(valores), 1) if valores else None,
        "dias_con_dato": len(valores),
        "dias_esperados": esperados,
        "completitud_pct": round(completitud, 1) if completitud is not None else None,
        "confiable": calidad["confiable"],
    }


def _rango_mes(anio_inicio: int, mes: int) -> tuple[date, date]:
    anio = anio_inicio + (mes < MES_INICIO_ANIO_AGRICOLA)
    return date(anio, mes, 1), date(anio, mes, monthrange(anio, mes)[1])


def _meses_en_rango(inicio: date, fin: date):
    anio, mes = inicio.year, inicio.month
    while (anio, mes) <= (fin.year, fin.month):
        yield anio, mes
        mes += 1
        if mes > 12:
            anio += 1
            mes = 1


def _anios_disponibles(fechas) -> set[int]:
    return {
        fecha.year if fecha.month >= MES_INICIO_ANIO_AGRICOLA else fecha.year - 1
        for fecha in fechas
    }


def _fecha_en_anio(fecha: date, anio: int) -> date:
    dia = min(fecha.day, monthrange(anio, fecha.month)[1])
    return date(anio, fecha.month, dia)


def _promedio_historico(
    lluvia,
    anios,
    anio_actual,
    rango,
    hoy,
    umbral,
    incluir_actual=False,
    fecha_corte: date | None = None,
    inicio_actual: date | None = None,
) -> tuple[float | None, int]:
    valores = []
    for anio in anios:
        if anio == anio_actual and not incluir_actual:
            continue
        inicio, fin = rango(anio)
        if fin > hoy:
            continue
        if fecha_corte is not None and inicio_actual is not None:
            desplazamiento_anual = fecha_corte.year - inicio_actual.year
            corte = _fecha_en_anio(fecha_corte, inicio.year + desplazamiento_anual)
            fin = min(fin, corte)
        medicion = _medir(lluvia, inicio, fin, hoy, umbral)
        if medicion["confiable"]:
            valores.append(medicion["mm"])
    cantidad = len(valores)
    if cantidad < MIN_TEMPORADAS_PROMEDIO:
        return None, cantidad
    return round(sum(valores) / cantidad, 1), cantidad


def _diferencia_pct(valor, promedio):
    if valor is None or promedio in (None, 0):
        return None
    return round((valor - promedio) / promedio * 100, 1)


def lluvia_fuera_invierno(
    estacion: Estacion,
    temporada: str,
    hoy: date | None = None,
    umbral_lluvia_intensa_mm: float | None = None,
    factor_mes_inusual: float | None = None,
) -> dict:
    """Calcula lluvia del año agrícola y eventos de octubre a abril, sin clasificarla."""
    hoy = hoy or timezone.localdate()
    umbral_calidad = ConfiguracionCalidad.obtener_umbral()
    umbral_lluvia_intensa = (
        umbral_lluvia_intensa_mm
        if umbral_lluvia_intensa_mm is not None
        else getattr(settings, "UMBRAL_LLUVIA_INTENSA_MM", 10.0)
    )
    factor_inusual = (
        factor_mes_inusual
        if factor_mes_inusual is not None
        else getattr(settings, "FACTOR_MES_INUSUAL", 2.0)
    )

    filas = list(
        ResumenDiario.objects.filter(estacion=estacion)
        .order_by("fecha")
        .values_list("fecha", "precipitacion", "origen")
    )
    lluvia = {fecha: valor for fecha, valor, _ in filas}
    origenes = {fecha: origen for fecha, _, origen in filas}
    anios = _anios_disponibles(lluvia)
    inicio_anio_agricola, _ = rango_anio_agricola(temporada)
    anio = inicio_anio_agricola.year

    rangos = {
        "total_anio_agricola": rango_anio_agricola(temporada),
        "septiembre": rango_septiembre(temporada),
        "crecimiento": rango_crecimiento(temporada),
        **{
            f"etapa_{nombre}": rango
            for nombre, rango in rangos_etapas_crecimiento(temporada).items()
        },
    }
    mediciones = {
        nombre: _medir(lluvia, inicio, fin, hoy, umbral_calidad)
        for nombre, (inicio, fin) in rangos.items()
    }
    codigos_etapas = "_".join(
        f"{inicio:%d%m}-{fin:%d%m}" for inicio, fin in rangos_etapas_crecimiento(temporada).values()
    )
    version = (
        f"lluvia-fuera-invierno-v2_ini{MES_INICIO_ANIO_AGRICOLA}_r{umbral_lluvia_intensa:g}mm_"
        f"mes{factor_inusual:g}x_min{MIN_TEMPORADAS_PROMEDIO}_{codigos_etapas}"
    )
    calidad_ventanas = {
        nombre: construir_calidad_dato(
            mediciones[nombre]["completitud_pct"],
            mediciones[nombre]["confiable"],
            umbral_calidad,
            resolucion_desde_origenes(
                origen for fecha, origen in origenes.items() if inicio <= fecha <= min(fin, hoy)
            ),
            version,
        )
        for nombre, (inicio, fin) in rangos.items()
    }

    etapas = []
    rangos_etapas = rangos_etapas_crecimiento(temporada)
    for nombre, (inicio, fin) in rangos_etapas.items():
        medicion = mediciones[f"etapa_{nombre}"]
        en_curso = fin > hoy
        evaluado_hasta = min(fin, hoy) if inicio <= hoy else None
        promedio, temporadas_en_promedio = _promedio_historico(
            lluvia,
            anios,
            anio,
            lambda anio_ref, etapa=nombre: rangos_etapas_crecimiento(f"{anio_ref}-{anio_ref + 1}")[
                etapa
            ],
            hoy,
            umbral_calidad,
            incluir_actual=True,
            fecha_corte=evaluado_hasta if en_curso else None,
            inicio_actual=inicio,
        )
        etapas.append(
            {
                "etapa": nombre,
                "desde": inicio.isoformat(),
                "hasta": fin.isoformat(),
                "mm": medicion["mm"],
                "promedio_mm": promedio,
                "diferencia_pct": (
                    _diferencia_pct(medicion["mm"], promedio) if medicion["confiable"] else None
                ),
                "temporadas_en_promedio": temporadas_en_promedio,
                "en_curso": en_curso,
                "evaluado_hasta": evaluado_hasta.isoformat() if evaluado_hasta else None,
            }
        )

    dias_lluvia_intensa = []
    inicio_crecimiento, fin_crecimiento = rango_crecimiento(temporada)
    for fecha, mm in sorted(lluvia.items()):
        if (
            inicio_crecimiento <= fecha <= min(fin_crecimiento, hoy)
            and mm is not None
            and mm >= umbral_lluvia_intensa
        ):
            etapa = next(
                (
                    nombre
                    for nombre, (inicio, fin) in rangos_etapas.items()
                    if inicio <= fecha <= fin
                ),
                None,
            )
            if etapa is not None:
                dias_lluvia_intensa.append(
                    {"fecha": fecha.isoformat(), "mm": round(mm, 1), "etapa": etapa}
                )

    meses_inusuales = []
    inicio_crecimiento, fin_crecimiento = rango_crecimiento(temporada)
    for _, mes in _meses_en_rango(inicio_crecimiento, fin_crecimiento):
        inicio, fin = _rango_mes(anio, mes)
        medicion = _medir(lluvia, inicio, fin, hoy, umbral_calidad)
        promedio, temporadas_en_promedio = _promedio_historico(
            lluvia,
            anios,
            anio,
            lambda anio_ref, mes=mes: _rango_mes(anio_ref, mes),
            hoy,
            umbral_calidad,
            incluir_actual=True,
        )
        mm = medicion["mm"]
        if (
            medicion["confiable"]
            and mm is not None
            and mm >= umbral_lluvia_intensa
            and promedio is not None
            and mm >= factor_inusual * promedio
        ):
            meses_inusuales.append(
                {
                    "mes": inicio.strftime("%Y-%m"),
                    "mm": mm,
                    "promedio_mm": promedio,
                    "temporadas_en_promedio": temporadas_en_promedio,
                }
            )

    ventanas_evaluadas = {
        nombre: calidad for nombre, calidad in calidad_ventanas.items() if rangos[nombre][0] <= hoy
    }
    calidades = list(ventanas_evaluadas.values())
    completitudes = [
        item["completitud_pct"] for item in calidades if item["completitud_pct"] is not None
    ]
    inicio_anio, fin_anio = rango_anio_agricola(temporada)
    calidad_dato = construir_calidad_dato(
        min(completitudes) if completitudes else None,
        bool(calidades) and all(item["confiable"] for item in calidades),
        umbral_calidad,
        resolucion_desde_origenes(
            origen
            for fecha, origen in origenes.items()
            if inicio_anio <= fecha <= min(fin_anio, hoy)
        ),
        version,
    )
    calidad_dato.update(
        {
            "ventanas": calidad_ventanas,
            "en_curso": fin_anio > hoy,
            "evaluado_hasta": min(fin_anio, hoy).isoformat() if inicio_anio <= hoy else None,
        }
    )
    resultado = {
        "total_anio_agricola_mm": mediciones["total_anio_agricola"]["mm"],
        "septiembre_mm": mediciones["septiembre"]["mm"],
        "crecimiento_mm": mediciones["crecimiento"]["mm"],
        "etapas": etapas,
        "dias_lluvia_intensa": dias_lluvia_intensa,
        "meses_inusuales": meses_inusuales,
        "calidad_dato": calidad_dato,
    }
    if resultado["total_anio_agricola_mm"] is None:
        resultado["motivo_nulo"] = "Sin datos de precipitación en el año agrícola."
    return resultado
