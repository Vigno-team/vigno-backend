from calendar import monthrange
from datetime import date, timedelta

MES_INICIO_TEMPORADA = 7

# Período invernal. Valores por temporales, hay que CONFIRMAR con el enólogo.
MES_INICIO_INVIERNO = 5  # mayo
MES_FIN_INVIERNO = 8  # agosto


def temporada_de(fecha: date) -> str:
    inicio = fecha.year if fecha.month >= MES_INICIO_TEMPORADA else fecha.year - 1
    return f"{inicio}-{inicio + 1}"


def rango_de(temporada: str) -> tuple[date, date]:
    inicio = int(temporada[:4])
    return date(inicio, MES_INICIO_TEMPORADA, 1), date(
        inicio + 1, MES_INICIO_TEMPORADA, 1
    ) - timedelta(days=1)


def rango_invernal(temporada: str) -> tuple[date, date]:
    anio = int(temporada[:4])
    inicio = date(anio, MES_INICIO_INVIERNO, 1)
    fin = date(anio, MES_FIN_INVIERNO, monthrange(anio, MES_FIN_INVIERNO)[1])
    return inicio, fin
