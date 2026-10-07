from datetime import date

from apps.clima.dias_criticos import calcular_dias_sobre_umbral
from apps.clima.models import ConfiguracionCalidad, Estacion, IndiceClimatico, ResumenDiario


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


def rango_temporada(temporada: str, tipo: str) -> tuple[date, date]:
    """
    Recibe "2024-2025" y devuelve el rango para Winkler o Huglin en hemisferio sur.
    """
    partes = temporada.split("-")
    anio_inicio = int(partes[0])
    anio_fin = int(partes[1])

    ini = date(anio_inicio, 10, 1)
    if tipo == "Winkler":
        fin = date(anio_fin, 4, 30)
    else:
        fin = date(anio_fin, 3, 31)
    return ini, fin


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


def calcular_indice_winkler(estacion: Estacion, temporada: str) -> None:
    ini, fin = rango_temporada(temporada, "Winkler")
    dias = ResumenDiario.objects.filter(estacion=estacion, fecha__range=[ini, fin])

    total_winkler = 0.0
    dias_con_dato = 0
    dias_esperados = (fin - ini).days + 1

    for d in dias:
        aporte = aporte_winkler(d)
        if aporte is not None:
            dias_con_dato += 1
            total_winkler += aporte

    if dias_con_dato == 0:
        return

    umbral = ConfiguracionCalidad.obtener_umbral()
    completitud = (dias_con_dato / dias_esperados * 100.0) if dias_esperados > 0 else 0
    confiable = completitud >= umbral

    total_winkler = round(total_winkler, 1)
    clasificacion = clasificar_winkler(total_winkler) if confiable else "Sin datos suficientes"

    IndiceClimatico.objects.update_or_create(
        estacion=estacion,
        temporada=temporada,
        indice="Winkler",
        defaults={
            "valor": total_winkler,
            "parametros": {
                "fecha_inicio": str(ini),
                "fecha_fin": str(fin),
                "temp_base": 10.0,
                "completitud_pct": completitud,
            },
            "confiable": confiable,
            "dias_con_dato": dias_con_dato,
            "dias_esperados": dias_esperados,
            "clasificacion": clasificacion,
            "version_calculo": "winkler-v1_base10_1001-0430",
        },
    )


def calcular_indice_huglin(estacion: Estacion, temporada: str) -> None:
    ini, fin = rango_temporada(temporada, "Huglin")
    dias = ResumenDiario.objects.filter(estacion=estacion, fecha__range=[ini, fin])

    total_huglin = 0.0
    dias_con_dato = 0
    dias_esperados = (fin - ini).days + 1
    k = k_huglin(estacion.latitud)

    for d in dias:
        aporte = aporte_huglin(d, k)
        if aporte is not None:
            dias_con_dato += 1
            total_huglin += aporte

    if dias_con_dato == 0:
        return

    umbral = ConfiguracionCalidad.obtener_umbral()
    completitud = (dias_con_dato / dias_esperados * 100.0) if dias_esperados > 0 else 0
    confiable = completitud >= umbral and estacion.latitud is not None

    total_huglin = round(total_huglin, 1)
    clasificacion = clasificar_huglin(total_huglin) if confiable else "Sin datos suficientes"

    IndiceClimatico.objects.update_or_create(
        estacion=estacion,
        temporada=temporada,
        indice="Huglin",
        defaults={
            "valor": total_huglin,
            "parametros": {
                "fecha_inicio": str(ini),
                "fecha_fin": str(fin),
                "k": k,
                "latitud": estacion.latitud,
                "temp_base": 10.0,
                "completitud_pct": completitud,
            },
            "confiable": confiable,
            "dias_con_dato": dias_con_dato,
            "dias_esperados": dias_esperados,
            "clasificacion": clasificacion,
            "version_calculo": "huglin-v1_base10_1001-0331",
        },
    )


def calcular_indices_temporada(estacion: Estacion, temporada: str):
    calcular_indice_winkler(estacion, temporada)
    calcular_indice_huglin(estacion, temporada)
    calcular_dias_sobre_umbral(estacion, temporada)
