"""E1C-120: cálculos compartidos, sin escrituras en la base.

Las ventanas pertenecen a temporadas.py. Los consumidores deciden el corte;
sin corte se evalúa la ventana completa (persistencia del pipeline).
"""

from datetime import date

from django.conf import settings

from apps.clima.models import ConfiguracionCalidad, Estacion, ResumenDiario
from apps.clima.temporadas import rango_dias_calor, rango_huglin, rango_invernal, rango_winkler


def k_huglin(latitud: float) -> float:
    if latitud is None:
        return 1.00
    lat = abs(latitud)
    if lat <= 40:
        return 1.00
    if lat <= 42:
        return 1.02
    if lat <= 44:
        return 1.03
    if lat <= 46:
        return 1.04
    if lat <= 48:
        return 1.05
    return 1.06


def clasificar_winkler(valor: float) -> str:
    if valor <= 1389:
        return "Región I"
    if valor <= 1667:
        return "Región II"
    if valor <= 1944:
        return "Región III"
    if valor <= 2222:
        return "Región IV"
    return "Región V"


def clasificar_huglin(valor: float) -> str:
    if valor <= 1500:
        return "Muy frío"
    if valor <= 1800:
        return "Frío"
    if valor <= 2100:
        return "Templado"
    if valor <= 2400:
        return "Templado cálido"
    if valor <= 3000:
        return "Cálido"
    return "Muy cálido"


def aporte_winkler(d: ResumenDiario) -> float | None:
    """Grados-día Winkler de un día; None si el día no tiene datos para calcularlo."""
    # Usa tmedia si existe, si no lo aproxima
    if d.tmedia is not None:
        tmedia = d.tmedia
    elif d.tmax is not None and d.tmin is not None:
        tmedia = (d.tmax + d.tmin) / 2.0
    else:
        return None
    return tmedia - 10.0 if tmedia > 10.0 else 0.0


def aporte_huglin(d: ResumenDiario, k: float) -> float | None:
    """Aporte diario al índice de Huglin; None si el día no tiene datos para calcularlo."""
    if d.tmax is None:
        return None
    if d.tmedia is not None:
        tmedia = d.tmedia
    elif d.tmin is not None:
        tmedia = (d.tmax + d.tmin) / 2.0
    else:
        return None
    calculo_diario = ((tmedia - 10.0) + (d.tmax - 10.0)) / 2.0
    return calculo_diario * k if calculo_diario > 0 else 0.0


def _winkler(dias, estacion):
    aportes = [a for d in dias if (a := aporte_winkler(d)) is not None]
    return (round(sum(aportes), 1) if aportes else None), len(aportes)


def _huglin(dias, estacion):
    k = k_huglin(estacion.latitud)
    aportes = [a for d in dias if (a := aporte_huglin(d, k)) is not None]
    return (round(sum(aportes), 1) if aportes else None), len(aportes)


def _dias_sobre_umbral(dias, estacion):
    umbral_c = float(settings.UMBRAL_CALOR_C)
    con_dato = [d for d in dias if d.tmax is not None]
    return (sum(d.tmax >= umbral_c for d in con_dato) if con_dato else None), len(con_dato)


def _lluvia(dias, estacion):
    mm = [d.precipitacion for d in dias if d.precipitacion is not None]
    return (round(sum(mm), 1) if mm else None), len(mm)


# nombre: (unidad, ventana de la temporada, función que calcula (valor, días con dato))
METRICAS = {
    "winkler": ("°C·día", rango_winkler, _winkler),
    "huglin": ("°C·día", rango_huglin, _huglin),
    "dias_sobre_umbral": ("días", rango_dias_calor, _dias_sobre_umbral),
    "lluvia_invernal": ("mm", rango_invernal, _lluvia),
}


def calidad_metrica(dias_con_dato, dias_esperados, umbral, *, habilitada=True):
    """Porcentaje sin redondear y confiabilidad; ausencia nunca equivale a cero observado."""
    completitud = (
        min(max(dias_con_dato / dias_esperados * 100, 0), 100) if dias_esperados > 0 else None
    )
    return {
        "completitud_pct": completitud,
        "confiable": bool(
            habilitada and dias_con_dato > 0 and completitud is not None and completitud >= umbral
        ),
    }


def valor_metrica(
    estacion: Estacion,
    metrica: str,
    temporada: str,
    corte: date | None = None,
    umbral: float | None = None,
    *,
    para_guardar: bool = False,
) -> dict:
    """Calcula una métrica con conteos y calidad sobre una única ventana.

    Por defecto conserva el contrato usado por comparación. para_guardar=True
    entrega los defaults de IndiceClimatico, sin escribirlos. Un valor None
    indica que no debe persistirse un índice; 0 sí es un resultado válido.
    """
    _, ventana, calculo = METRICAS[metrica]
    inicio, fin = ventana(temporada)
    hasta = min(fin, corte) if corte is not None else fin
    esperados = max((hasta - inicio).days + 1, 0)
    dias = (
        list(ResumenDiario.objects.filter(estacion=estacion, fecha__range=(inicio, hasta)))
        if esperados
        else []
    )
    valor, n = calculo(dias, estacion)
    umbral = ConfiguracionCalidad.obtener_umbral() if umbral is None else umbral
    calidad = calidad_metrica(
        n, esperados, umbral, habilitada=metrica != "huglin" or estacion.latitud is not None
    )
    completitud = calidad["completitud_pct"]
    resultado = {
        "valor": valor,
        "dias_con_dato": n,
        "dias_esperados": esperados,
        "completitud_pct": round(completitud, 1) if completitud is not None else None,
        "confiable": calidad["confiable"],
        "hasta": hasta.isoformat(),
    }
    if not para_guardar:
        return resultado
    parametros = {
        "fecha_inicio": inicio.isoformat(),
        "fecha_fin": hasta.isoformat(),
        "completitud_pct": completitud,
    }
    clasificacion = None
    if metrica in ("winkler", "huglin"):
        parametros["temp_base"] = 10.0
        clasificar = clasificar_winkler if metrica == "winkler" else clasificar_huglin
        clasificacion = clasificar(valor) if calidad["confiable"] else "Sin datos suficientes"
        version = (
            "winkler-v1_base10_1001-0430" if metrica == "winkler" else "huglin-v1_base10_1001-0331"
        )
        if metrica == "huglin":
            parametros.update(k=k_huglin(estacion.latitud), latitud=estacion.latitud)
    elif metrica == "dias_sobre_umbral":
        umbral_c = float(settings.UMBRAL_CALOR_C)
        parametros["umbral_tmax"] = umbral_c
        version = f"dias_umbral-v2_{umbral_c:g}c_{inicio:%m%d}-{fin:%m%d}"
    else:
        version = f"lluvia-invernal-v1_{inicio:%d%m}-{fin:%d%m}"
    return {
        "valor": float(valor) if valor is not None else None,
        "dias_con_dato": n,
        "dias_esperados": esperados,
        "confiable": calidad["confiable"],
        "parametros": parametros,
        "clasificacion": clasificacion,
        "version_calculo": version,
    }
