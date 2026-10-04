from datetime import date

from apps.clima.models import ConfiguracionCalidad, Estacion, IndiceClimatico, ResumenDiario


def ventana_verano(temporada: str) -> tuple[date, date]:
    inicio = int(temporada[:4])
    return date(inicio, 10, 1), date(inicio + 1, 4, 30)


def calcular_dias_sobre_umbral(estacion: Estacion, temporada: str, umbral: float = 35.0) -> int:
    resumenes = ResumenDiario.objects.filter(estacion=estacion, temporada=temporada)
    dias_count = resumenes.filter(tmax__gte=umbral).count()

    ini, fin = ventana_verano(temporada)
    dias_esperados = (fin - ini).days + 1
    dias_con_dato = resumenes.filter(fecha__range=[ini, fin], tmax__isnull=False).count()
    if dias_con_dato == 0:
        return dias_count

    completitud = dias_con_dato / dias_esperados * 100.0
    confiable = completitud >= ConfiguracionCalidad.obtener_umbral()

    IndiceClimatico.objects.update_or_create(
        estacion=estacion,
        temporada=temporada,
        indice="DiasSobreUmbral",
        defaults={
            "valor": float(dias_count),
            "parametros": {
                "umbral_tmax": umbral,
                "fecha_inicio": str(ini),
                "fecha_fin": str(fin),
                "completitud_pct": completitud,
            },
            "confiable": confiable,
            "dias_con_dato": dias_con_dato,
            "dias_esperados": dias_esperados,
            "clasificacion": None,
            "version_calculo": f"dias_umbral-v1_{umbral:g}c",
        },
    )
    return dias_count


def obtener_dias_criticos(estacion: Estacion, temporada: str, limite: int = 10) -> list[dict]:
    if limite <= 0:
        raise ValueError("limite debe ser mayor a 0.")
    dias_criticos = ResumenDiario.objects.filter(
        estacion=estacion, temporada=temporada, tmax__isnull=False
    ).order_by("-tmax", "fecha")[:limite]

    return [{"fecha": str(d.fecha), "tmax": d.tmax} for d in dias_criticos]
