from datetime import date, timedelta

MES_INICIO_TEMPORADA = 7


def temporada_de(fecha: date) -> str:
    inicio = fecha.year if fecha.month >= MES_INICIO_TEMPORADA else fecha.year - 1
    return f"{inicio}-{inicio + 1}"


def rango_de(temporada: str) -> tuple[date, date]:
    inicio = int(temporada[:4])
    return date(inicio, MES_INICIO_TEMPORADA, 1), date(
        inicio + 1, MES_INICIO_TEMPORADA, 1
    ) - timedelta(days=1)
