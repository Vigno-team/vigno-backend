from apps.clima.models import Estacion, IndiceClimatico, ResumenDiario


def calcular_dias_sobre_umbral(estacion: Estacion, temporada: str, umbral: float = 35.0) -> int:
    dias_count = ResumenDiario.objects.filter(
        estacion=estacion,
        temporada=temporada,
        tmax__gte=umbral
    ).count()

    IndiceClimatico.objects.update_or_create(
        estacion=estacion,
        temporada=temporada,
        indice="DiasSobreUmbral",
        defaults={
            "valor": float(dias_count),
            "parametros": {"umbral_tmax": umbral},
            "confiable": True,
            "clasificacion": "Estrés térmico" if dias_count > 0 else "Normal",
            "version_calculo": "dias_umbral-v1",
        },
    )
    return dias_count


def obtener_dias_criticos(estacion: Estacion, temporada: str, limite: int = 10) -> list[dict]:
    dias_criticos = ResumenDiario.objects.filter(
        estacion=estacion,
        temporada=temporada,
        tmax__isnull=False
    ).order_by("-tmax", "fecha")[:limite]

    return [
        {
            "fecha": str(d.fecha),
            "tmax": d.tmax
        }
        for d in dias_criticos
    ]