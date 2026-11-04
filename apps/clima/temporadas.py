from calendar import monthrange
from datetime import date, timedelta

from django.conf import settings

MIN_TEMPORADAS_PROMEDIO = 2


def calendario():
    return settings.INSTANCIA["calendario"]


def mes_inicio_anio_agricola():
    return calendario()["mes_inicio_anio_agricola"]


def temporada_de(fecha: date) -> str:
    inicio = fecha.year if fecha.month >= calendario()["mes_inicio_temporada"] else fecha.year - 1
    return f"{inicio}-{inicio + 1}"


def _anio_inicio(temporada: str) -> int:
    return int(temporada[:4])


def rango_temporada(temporada: str) -> tuple[date, date]:
    inicio = _anio_inicio(temporada)
    mes = calendario()["mes_inicio_temporada"]
    primer_dia = date(inicio, mes, 1)
    siguiente = date(inicio + 1, mes, 1)
    return primer_dia, siguiente - timedelta(days=1)


def rango_invernal(temporada: str) -> tuple[date, date]:
    cal = calendario()
    meses = cal["meses_invierno"]
    anio = _anio_inicio(temporada) + cal["desfase_anio_invierno"]
    inicio = date(anio, meses[0], 1)
    anio_fin = anio + (meses[-1] < meses[0])
    fin = date(anio_fin, meses[-1], monthrange(anio_fin, meses[-1])[1])
    return inicio, fin


def _fecha(anio, mes_dia):
    mes, dia = mes_dia
    return date(anio, mes, min(dia, monthrange(anio, mes)[1]))


def _ventana_indice(temporada, nombre):
    cal = calendario()
    ventana = cal["ventanas_indices"][nombre]
    anio = _anio_inicio(temporada) + (ventana["inicio"][0] < cal["mes_inicio_temporada"])
    fin_anio = anio + (tuple(ventana["fin"]) < tuple(ventana["inicio"]))
    return _fecha(anio, ventana["inicio"]), _fecha(fin_anio, ventana["fin"])


def rango_winkler(temporada: str) -> tuple[date, date]:
    return _ventana_indice(temporada, "winkler")


def rango_huglin(temporada: str) -> tuple[date, date]:
    return _ventana_indice(temporada, "huglin")


def rango_dias_calor(temporada: str) -> tuple[date, date]:
    return _ventana_indice(temporada, "dias_calor")


def rango_anio_agricola(temporada: str) -> tuple[date, date]:
    inicio = _anio_inicio(temporada)
    mes = mes_inicio_anio_agricola()
    primer_dia = date(inicio, mes, 1)
    siguiente = date(inicio + 1, mes, 1)
    return primer_dia, siguiente - timedelta(days=1)


def rango_precrecimiento(temporada: str) -> tuple[date, date]:
    inicio, _ = rango_crecimiento(temporada)
    fin = inicio.replace(day=1) - timedelta(days=1)
    return fin.replace(day=1), fin


def rango_crecimiento(temporada: str) -> tuple[date, date]:
    etapas = rangos_etapas_crecimiento(temporada).values()
    inicios = [inicio for inicio, _ in etapas]
    fines = [fin for _, fin in etapas]
    return min(inicios), max(fines)


def rangos_etapas_crecimiento(temporada: str) -> dict[str, tuple[date, date]]:
    anio = _anio_inicio(temporada)
    rangos = {}
    mes_agricola = mes_inicio_anio_agricola()
    for etapa in calendario()["etapas_crecimiento"]:
        anio_inicio = anio + (etapa["inicio"][0] < mes_agricola)
        anio_fin = anio + (etapa["fin"][0] < mes_agricola)
        rangos[etapa["nombre"]] = (
            _fecha(anio_inicio, etapa["inicio"]),
            _fecha(anio_fin, etapa["fin"]),
        )
    return rangos
