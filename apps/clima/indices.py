"""Persistencia de los resultados calculados por metricas.py."""

from apps.clima import metricas
from apps.clima.models import Estacion, IndiceClimatico

NOMBRES_INDICE = {"winkler": "Winkler", "huglin": "Huglin", "dias_sobre_umbral": "DiasSobreUmbral"}


def _guardar(estacion: Estacion, temporada: str, metrica: str):
    resultado = metricas.valor_metrica(estacion, metrica, temporada, para_guardar=True)
    if resultado["valor"] is not None:
        IndiceClimatico.objects.update_or_create(
            estacion=estacion,
            temporada=temporada,
            indice=NOMBRES_INDICE[metrica],
            defaults=resultado,
        )
    return resultado["valor"]


def calcular_indice_winkler(estacion: Estacion, temporada: str) -> None:
    _guardar(estacion, temporada, "winkler")


def calcular_indice_huglin(estacion: Estacion, temporada: str) -> None:
    _guardar(estacion, temporada, "huglin")


def calcular_dias_sobre_umbral(estacion: Estacion, temporada: str) -> int:
    return int(_guardar(estacion, temporada, "dias_sobre_umbral") or 0)


def calcular_indices_temporada(estacion: Estacion, temporada: str):
    calcular_indice_winkler(estacion, temporada)
    calcular_indice_huglin(estacion, temporada)
    calcular_dias_sobre_umbral(estacion, temporada)
