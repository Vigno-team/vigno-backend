"""Contrato de intercambio provisional con D1.3; no persiste datos de cosecha."""

import math
import re
from datetime import date

from apps.clima.temporadas import rango_de, temporada_de


def _numero(valor):
    return isinstance(valor, int | float) and not isinstance(valor, bool) and math.isfinite(valor)


def validar_historico(documento):
    if not isinstance(documento, dict) or documento.get("version") != "1":
        raise ValueError("El histórico debe ser un objeto con version='1'.")
    escala = documento.get("escala_calidad")
    if (
        not isinstance(escala, dict)
        or not isinstance(escala.get("nombre"), str)
        or not escala["nombre"].strip()
    ):
        raise ValueError("Declare el nombre y tipo de escala_calidad acordados con el enólogo.")
    tipo = escala.get("tipo")
    if tipo == "numerica":
        if (
            not _numero(escala.get("minimo"))
            or not _numero(escala.get("maximo"))
            or escala["minimo"] >= escala["maximo"]
        ):
            raise ValueError("La escala numérica requiere minimo < maximo, ambos finitos.")
    elif tipo == "ordinal":
        orden = escala.get("orden")
        if (
            not isinstance(orden, list)
            or len(orden) < 2
            or any(not isinstance(v, str) or not v.strip() for v in orden)
            or len(set(orden)) != len(orden)
        ):
            raise ValueError(
                "La escala ordinal requiere orden: categorías distintas, de menor a mayor calidad."
            )
    else:
        raise ValueError("El tipo de escala debe ser numerica u ordinal.")
    registros = documento.get("registros")
    if not isinstance(registros, list) or not registros:
        raise ValueError("registros debe ser una lista no vacía con el histórico real.")
    vistos = set()
    resultado = []
    for numero, fila in enumerate(registros, 1):
        if not isinstance(fila, dict):
            raise ValueError(f"Fila {numero}: se esperaba un objeto.")
        for campo in ("subzona", "cepa", "temporada"):
            if not isinstance(fila.get(campo), str) or not fila[campo].strip():
                raise ValueError(f"Fila {numero}: falta {campo}.")
        temporada = fila["temporada"]
        if (
            not re.fullmatch(r"\d{4}-\d{4}", temporada)
            or int(temporada[5:]) != int(temporada[:4]) + 1
        ):
            raise ValueError(f"Fila {numero}: temporada inválida; use YYYY-YYYY consecutivos.")
        inicio, _ = rango_de(temporada)
        clave = (fila["subzona"], fila["cepa"], temporada)
        if clave in vistos:
            raise ValueError(
                f"Fila {numero}: duplicado subzona/cepa/temporada; acuerde la agregación con D1.3."
            )
        vistos.add(clave)
        fecha = fila.get("fecha_cosecha")
        dia = None
        if fecha is not None:
            if not isinstance(fecha, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha):
                raise ValueError(f"Fila {numero}: fecha_cosecha debe ser YYYY-MM-DD o null.")
            cosecha = date.fromisoformat(fecha)
            if temporada_de(cosecha) != temporada:
                raise ValueError(
                    f"Fila {numero}: fecha de cosecha fuera de su temporada (julio-junio)."
                )
            dia = (cosecha - inicio).days
        calidad = fila.get("calidad")
        if calidad is not None:
            if tipo == "numerica":
                if not _numero(calidad) or not escala["minimo"] <= calidad <= escala["maximo"]:
                    raise ValueError(f"Fila {numero}: calidad fuera de la escala numérica.")
            else:
                if calidad not in escala["orden"]:
                    raise ValueError(f"Fila {numero}: categoría de calidad desconocida.")
                calidad = escala["orden"].index(calidad)
        resultado.append({**fila, "dia_cosecha": dia, "calidad_numerica": calidad})
    return resultado
