from calendar import monthrange
from datetime import date, timedelta

MES_INICIO_TEMPORADA = 7

# Período invernal. Valores por temporales, hay que CONFIRMAR con el enólogo.
MES_INICIO_INVIERNO = 5  # mayo
MES_FIN_INVIERNO = 8  # agosto
MES_INICIO_ANIO_AGRICOLA = 5  # mayo

ETAPAS_CRECIMIENTO = (
    ("brotacion_floracion", (10, 1), (11, 30)),
    ("cuaja_envero", (12, 1), (1, 31)),
    ("maduracion_cosecha", (2, 1), (4, 30)),
)


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


def rango_anio_agricola(temporada: str) -> tuple[date, date]:
    anio = int(temporada[:4])
    inicio = date(anio, MES_INICIO_ANIO_AGRICOLA, 1)
    fin = date(anio + 1, MES_INICIO_ANIO_AGRICOLA, 1) - timedelta(days=1)
    return inicio, fin


def rango_septiembre(temporada: str) -> tuple[date, date]:
    anio = int(temporada[:4])
    return date(anio, 9, 1), date(anio, 9, monthrange(anio, 9)[1])


def rango_crecimiento(temporada: str) -> tuple[date, date]:
    anio = int(temporada[:4])
    return date(anio, 10, 1), date(anio + 1, 4, 30)


def rangos_etapas_crecimiento(temporada: str) -> dict[str, tuple[date, date]]:
    anio = int(temporada[:4])
    rangos = {}
    for etapa, (mes_inicio, dia_inicio), (mes_fin, dia_fin) in ETAPAS_CRECIMIENTO:
        anio_inicio = anio + (mes_inicio < MES_INICIO_ANIO_AGRICOLA)
        anio_fin = anio + (mes_fin < MES_INICIO_ANIO_AGRICOLA)
        rangos[etapa] = (
            date(anio_inicio, mes_inicio, dia_inicio),
            date(anio_fin, mes_fin, dia_fin),
        )
    return rangos
