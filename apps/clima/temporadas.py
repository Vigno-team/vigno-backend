from calendar import monthrange
from datetime import date, timedelta

MES_INICIO_TEMPORADA = 7

MES_INICIO_INVIERNO = 5  # mayo
MES_FIN_INVIERNO = 8  # agosto


def temporada_de(fecha: date) -> str:
    inicio = fecha.year if fecha.month >= MES_INICIO_TEMPORADA else fecha.year - 1
    return f"{inicio}-{inicio + 1}"


def _anio_inicio(temporada: str) -> int:
    return int(temporada[:4])


def rango_temporada(temporada: str) -> tuple[date, date]:
    inicio = _anio_inicio(temporada)
    primer_dia = date(inicio, MES_INICIO_TEMPORADA, 1)
    siguiente = date(inicio + 1, MES_INICIO_TEMPORADA, 1)
    return primer_dia, siguiente - timedelta(days=1)


def rango_invernal(temporada: str) -> tuple[date, date]:
    anio = _anio_inicio(temporada)
    inicio = date(anio, MES_INICIO_INVIERNO, 1)
    fin = date(anio, MES_FIN_INVIERNO, monthrange(anio, MES_FIN_INVIERNO)[1])
    return inicio, fin


def rango_winkler(temporada: str) -> tuple[date, date]:
    inicio = _anio_inicio(temporada)
    return date(inicio, 10, 1), date(inicio + 1, 4, 30)


def rango_huglin(temporada: str) -> tuple[date, date]:
    inicio = _anio_inicio(temporada)
    return date(inicio, 10, 1), date(inicio + 1, 3, 31)


def rango_dias_calor(temporada: str) -> tuple[date, date]:
    inicio = _anio_inicio(temporada)
    return date(inicio, 10, 1), date(inicio + 1, 4, 30)
