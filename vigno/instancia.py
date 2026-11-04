"""Contrato de instancia, compartido por settings, carga inicial y configuración."""

import json
import re
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ImproperlyConfigured


def _error(campo, detalle):
    raise ImproperlyConfigured(f"instancia.json: {campo}: {detalle}")


def _objeto(valor, campo, claves):
    if not isinstance(valor, dict) or set(valor) != set(claves):
        _error(campo, f"debe contener exactamente {', '.join(claves)}")


def _texto(valor, campo, maximo=100):
    if not isinstance(valor, str) or not valor.strip() or len(valor) > maximo:
        _error(campo, f"debe ser texto no vacío de hasta {maximo} caracteres")


def _mes(valor, campo):
    if type(valor) is not int or not 1 <= valor <= 12:
        _error(campo, "debe ser un entero entre 1 y 12")


def _mes_dia(valor, campo):
    if not isinstance(valor, list) or len(valor) != 2 or any(type(x) is not int for x in valor):
        _error(campo, "usa [mes, día]")
    try:
        date(2000, *valor)
    except ValueError:
        _error(campo, "mes o día inválido")


def validar_configuracion(datos):
    _objeto(
        datos,
        "raíz",
        (
            "version",
            "organizacion",
            "zona_horaria",
            "calendario",
            "json_salida",
            "limites_geograficos",
            "archivos",
        ),
    )
    if type(datos["version"]) is not int or datos["version"] != 1:
        _error("version", "solo se admite la versión 1")
    _objeto(datos["organizacion"], "organizacion", ("nombre", "nombre_corto"))
    for clave, valor in datos["organizacion"].items():
        _texto(valor, f"organizacion.{clave}")
    _texto(datos["zona_horaria"], "zona_horaria")
    try:
        ZoneInfo(datos["zona_horaria"])
    except (ZoneInfoNotFoundError, ValueError):
        _error("zona_horaria", "zona IANA desconocida")
    salida = datos["json_salida"]
    if not isinstance(salida, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.json", salida):
        _error("json_salida", "usa un nombre .json sin directorios")
    _objeto(datos["archivos"], "archivos", ("mapeos", "areas"))
    for clave, valor in datos["archivos"].items():
        _texto(valor, f"archivos.{clave}", 1024)
    limites = datos["limites_geograficos"]
    if (
        not isinstance(limites, dict)
        or not {"latitud", "longitud"} <= set(limites)
        or set(limites) - {"latitud", "longitud", "estaciones"}
    ):
        _error("limites_geograficos", "requiere latitud y longitud; estaciones es opcional")
    for eje, maximo in (("latitud", 90), ("longitud", 180)):
        par = limites[eje]
        if (
            not isinstance(par, list)
            or len(par) != 2
            or any(type(x) not in (int, float) for x in par)
            or not -maximo <= par[0] < par[1] <= maximo
        ):
            _error(f"limites_geograficos.{eje}", "intervalo geográfico inválido")
    if "estaciones" in limites:
        cajas = limites["estaciones"]
        if not isinstance(cajas, list) or not cajas:
            _error("limites_geograficos.estaciones", "lista no vacía de cajas geográficas")
        for caja in cajas:
            if (
                not isinstance(caja, list)
                or len(caja) != 4
                or any(type(x) not in (int, float) for x in caja)
                or not -90 <= caja[0] < caja[1] <= 90
                or not -180 <= caja[2] < caja[3] <= 180
            ):
                _error("limites_geograficos.estaciones", "usa [lat_min, lat_max, lon_min, lon_max]")
    cal = datos["calendario"]
    _objeto(
        cal,
        "calendario",
        (
            "mes_inicio_temporada",
            "mes_inicio_anio_agricola",
            "meses_invierno",
            "desfase_anio_invierno",
            "desfase_analogos_dias",
            "ventanas_indices",
            "etapas_crecimiento",
        ),
    )
    for clave in ("mes_inicio_temporada", "mes_inicio_anio_agricola"):
        _mes(cal[clave], f"calendario.{clave}")
    meses = cal["meses_invierno"]
    if (
        not isinstance(meses, list)
        or not 1 <= len(meses) <= 12
        or len(set(map(str, meses))) != len(meses)
    ):
        _error("calendario.meses_invierno", "lista ordenada de meses consecutivos sin repetidos")
    for mes in meses:
        _mes(mes, "calendario.meses_invierno")
    if any(b != a % 12 + 1 for a, b in zip(meses, meses[1:], strict=False)):
        _error(
            "calendario.meses_invierno",
            "los meses deben ser consecutivos, incluso al cruzar diciembre",
        )
    if type(cal["desfase_anio_invierno"]) is not int or cal["desfase_anio_invierno"] not in (
        -1,
        0,
        1,
    ):
        _error(
            "calendario.desfase_anio_invierno",
            "debe ser -1, 0 o 1 respecto al primer año de temporada",
        )
    ventanas = cal["ventanas_indices"]
    if (
        type(cal["desfase_analogos_dias"]) is not int
        or not -365 <= cal["desfase_analogos_dias"] <= 365
    ):
        _error("calendario.desfase_analogos_dias", "debe ser un entero entre -365 y 365")
    _objeto(ventanas, "calendario.ventanas_indices", ("winkler", "huglin", "dias_calor"))
    for nombre, ventana in ventanas.items():
        _objeto(ventana, nombre, ("inicio", "fin"))
        for extremo in ("inicio", "fin"):
            _mes_dia(ventana[extremo], f"{nombre}.{extremo}")
    etapas = cal["etapas_crecimiento"]
    if not isinstance(etapas, list) or not etapas:
        _error("calendario.etapas_crecimiento", "debe tener al menos una etapa")
    vistos, fin_anterior = set(), None
    for etapa in etapas:
        _objeto(etapa, "etapa", ("nombre", "inicio", "fin"))
        nombre = etapa["nombre"]
        if (
            not isinstance(nombre, str)
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,49}", nombre)
            or nombre in vistos
        ):
            _error("etapa.nombre", "usa identificadores únicos en minúsculas")
        vistos.add(nombre)
        for extremo in ("inicio", "fin"):
            _mes_dia(etapa[extremo], f"{nombre}.{extremo}")

        # Comparar dentro de un año agrícola abstracto, incluyendo el cruce de año.
        def posicion(md):
            return ((md[0] - cal["mes_inicio_anio_agricola"]) % 12, md[1])

        ini, fin = posicion(etapa["inicio"]), posicion(etapa["fin"])
        if fin < ini or (fin_anterior is not None and ini <= fin_anterior):
            _error(
                "etapas_crecimiento",
                "deben estar ordenadas, sin solaparse y dentro del año agrícola",
            )
        fin_anterior = fin
    return datos


def _pares_unicos(pares):
    objeto = {}
    for clave, valor in pares:
        if clave in objeto:
            _error(clave, "clave repetida")
        objeto[clave] = valor
    return objeto


def cargar_configuracion(ruta):
    try:
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"), object_pairs_hook=_pares_unicos)
    except (OSError, ValueError) as error:
        raise ImproperlyConfigured(f"No se pudo leer la instancia {ruta}: {error}") from error
    return validar_configuracion(datos)


def archivo_instancia(nombre):
    from django.conf import settings

    return settings.BASE_DIR / settings.INSTANCIA["archivos"][nombre]


def nombre_salida():
    from django.conf import settings

    return settings.INSTANCIA["json_salida"]
