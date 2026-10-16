from calendar import monthrange
from datetime import date

from django.conf import settings
from django.utils import timezone

from apps.clima.models import ConfiguracionCalidad, Estacion, ResumenDiario
from apps.clima.temporadas import (
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
    completitud = round(min(len(valores) / esperados * 100, 100), 1) if esperados else None
    return {
        "mm": round(sum(valores), 1) if valores else None,
        "dias_con_dato": len(valores),
        "dias_esperados": esperados,
        "completitud_pct": completitud,
        "confiable": completitud is not None and completitud >= umbral and bool(valores),
    }


def _resolucion(origenes, inicio: date, fin: date, hoy: date) -> str | None:
    hasta = min(fin, hoy)
    encontrados = {origen for fecha, origen in origenes.items() if inicio <= fecha <= hasta}
    if len(encontrados) > 1:
        return "mixta"
    return {"D": "diaria", "H": "horaria"}.get(next(iter(encontrados), None))


def _calidad(medicion, origenes, inicio, fin, hoy, umbral, version):
    return {
        "completitud_pct": medicion["completitud_pct"],
        "confiable": medicion["confiable"],
        "umbral_completitud_pct": umbral,
        "resolucion_origen": _resolucion(origenes, inicio, fin, hoy),
        "version_calculo": version,
    }


def _rango_mes(anio_inicio: int, mes: int) -> tuple[date, date]:
    anio = anio_inicio + (mes < 5)
    return date(anio, mes, 1), date(anio, mes, monthrange(anio, mes)[1])


def _anios_disponibles(fechas) -> set[int]:
    return {fecha.year if fecha.month >= 5 else fecha.year - 1 for fecha in fechas}


def _promedio_historico(lluvia, anios, anio_actual, rango, hoy, umbral, incluir_actual=False):
    valores = []
    for anio in anios:
        if anio == anio_actual and not incluir_actual:
            continue
        inicio, fin = rango(anio)
        if fin > hoy:
            continue
        medicion = _medir(lluvia, inicio, fin, hoy, umbral)
        if medicion["confiable"]:
            valores.append(medicion["mm"])
    return round(sum(valores) / len(valores), 1) if valores else None


def _diferencia_pct(valor, promedio):
    if valor is None or promedio in (None, 0):
        return None
    return round((valor - promedio) / promedio * 100, 1)


def lluvia_fuera_invierno(
    estacion_codigo: str,
    temporada: str,
    hoy: date | None = None,
    umbral_lluvia_intensa_mm: float | None = None,
    factor_mes_inusual: float | None = None,
) -> dict:
    """Calcula lluvia del año agrícola y eventos de octubre a abril, sin clasificarla."""
    estacion = Estacion.objects.get(codigo=estacion_codigo)
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
    anio = int(temporada[:4])

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
    version = f"lluvia-fuera-invierno-v1_r{umbral_lluvia_intensa:g}mm_mes{factor_inusual:g}x"
    calidad_ventanas = {
        nombre: _calidad(mediciones[nombre], origenes, inicio, fin, hoy, umbral_calidad, version)
        for nombre, (inicio, fin) in rangos.items()
    }

    etapas = []
    rangos_etapas = rangos_etapas_crecimiento(temporada)
    for nombre, (inicio, fin) in rangos_etapas.items():
        medicion = mediciones[f"etapa_{nombre}"]
        promedio = _promedio_historico(
            lluvia,
            anios,
            anio,
            lambda anio_ref, etapa=nombre: rangos_etapas_crecimiento(f"{anio_ref}-{anio_ref + 1}")[
                etapa
            ],
            hoy,
            umbral_calidad,
        )
        etapas.append(
            {
                "etapa": nombre,
                "desde": inicio.isoformat(),
                "hasta": fin.isoformat(),
                "mm": medicion["mm"],
                "promedio_mm": promedio,
                "diferencia_pct": _diferencia_pct(medicion["mm"], promedio),
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
                nombre for nombre, (inicio, fin) in rangos_etapas.items() if inicio <= fecha <= fin
            )
            dias_lluvia_intensa.append(
                {"fecha": fecha.isoformat(), "mm": round(mm, 1), "etapa": etapa}
            )

    meses_inusuales = []
    for mes in (10, 11, 12, 1, 2, 3, 4):
        inicio, fin = _rango_mes(anio, mes)
        medicion = _medir(lluvia, inicio, fin, hoy, umbral_calidad)
        promedio = _promedio_historico(
            lluvia,
            anios,
            inicio.year if inicio.month >= 5 else inicio.year - 1,
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
                {"mes": inicio.strftime("%Y-%m"), "mm": mm, "promedio_mm": promedio}
            )

    calidades = list(calidad_ventanas.values())
    completitudes = [
        item["completitud_pct"] for item in calidades if item["completitud_pct"] is not None
    ]
    inicio_anio, fin_anio = rango_anio_agricola(temporada)
    calidad_dato = {
        "completitud_pct": min(completitudes) if completitudes else None,
        "confiable": bool(calidades) and all(item["confiable"] for item in calidades),
        "umbral_completitud_pct": umbral_calidad,
        "resolucion_origen": _resolucion(origenes, inicio_anio, fin_anio, hoy),
        "version_calculo": version,
        "ventanas": calidad_ventanas,
    }
    return {
        "total_anio_agricola_mm": mediciones["total_anio_agricola"]["mm"],
        "septiembre_mm": mediciones["septiembre"]["mm"],
        "crecimiento_mm": mediciones["crecimiento"]["mm"],
        "etapas": etapas,
        "dias_lluvia_intensa": dias_lluvia_intensa,
        "meses_inusuales": meses_inusuales,
        "calidad_dato": calidad_dato,
    }
