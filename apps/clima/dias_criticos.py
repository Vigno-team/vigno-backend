from apps.clima.indices import calcular_dias_sobre_umbral as calcular_dias_sobre_umbral
from apps.clima.models import Estacion, ResumenDiario


def obtener_dias_criticos(estacion: Estacion, temporada: str, limite: int = 10) -> list[dict]:
    if limite <= 0:
        raise ValueError("limite debe ser mayor a 0.")
    dias_criticos = ResumenDiario.objects.filter(
        estacion=estacion, temporada=temporada, tmax__isnull=False
    ).order_by("-tmax", "fecha")[:limite]

    return [{"fecha": str(d.fecha), "tmax": d.tmax} for d in dias_criticos]
