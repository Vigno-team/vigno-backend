from calendar import monthrange
from datetime import date, timedelta

MES_INICIO_TEMPORADA = 7
MIN_TEMPORADAS_PROMEDIO = 2

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


def rango_anio_agricola(temporada: str) -> tuple[date, date]:
    inicio = _anio_inicio(temporada)
    primer_dia = date(inicio, MES_INICIO_ANIO_AGRICOLA, 1)
    siguiente = date(inicio + 1, MES_INICIO_ANIO_AGRICOLA, 1)
    return primer_dia, siguiente - timedelta(days=1)


def rango_septiembre(temporada: str) -> tuple[date, date]:
    anio = _anio_inicio(temporada)
    return date(anio, 9, 1), date(anio, 9, monthrange(anio, 9)[1])


def rango_crecimiento(temporada: str) -> tuple[date, date]:
    etapas = rangos_etapas_crecimiento(temporada).values()
    inicios = [inicio for inicio, _ in etapas]
    fines = [fin for _, fin in etapas]
    return min(inicios), max(fines)


def rangos_etapas_crecimiento(temporada: str) -> dict[str, tuple[date, date]]:
    anio = _anio_inicio(temporada)
    rangos = {}
    for etapa, (mes_inicio, dia_inicio), (mes_fin, dia_fin) in ETAPAS_CRECIMIENTO:
        anio_inicio = anio + (mes_inicio < MES_INICIO_ANIO_AGRICOLA)
        anio_fin = anio + (mes_fin < MES_INICIO_ANIO_AGRICOLA)
        rangos[etapa] = (
            date(anio_inicio, mes_inicio, dia_inicio),
            date(anio_fin, mes_fin, dia_fin),
        )
    return rangos
