"""E1C-58/59/60: asociación exploratoria, sin imputación ni predicción."""

import math
import random
from itertools import permutations

MIN_MUESTRA = 3
UMBRAL_HISTORICO_CORTO = 10
SEMILLA = 2026
REPETICIONES = 9999


def _rangos(valores):
    """Rangos medios para empates, comenzando en 1."""
    orden = sorted(range(len(valores)), key=valores.__getitem__)
    resultado = [0.0] * len(valores)
    inicio = 0
    while inicio < len(orden):
        fin = inicio + 1
        while fin < len(orden) and valores[orden[fin]] == valores[orden[inicio]]:
            fin += 1
        for posicion in orden[inicio:fin]:
            resultado[posicion] = (inicio + 1 + fin) / 2
        inicio = fin
    return resultado


def correlacion(x, y):
    """Spearman y p bilateral por |rho|; permuta solo un miembro de cada par.

    Exacta hasta n=8 (incluidos empates); Monte Carlo con semilla fija después.
    No usa el p asintótico, inadecuado para el histórico corto de este proyecto.
    """
    if len(x) != len(y):
        raise ValueError("Las dos series deben tener el mismo tamaño.")
    if any(
        isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v)
        for v in [*x, *y]
    ):
        raise ValueError("Las series deben contener números finitos.")
    n = len(x)
    resultado = {
        "n": n,
        "rho": None,
        "p_valor": None,
        "estado": "muestra_insuficiente",
        "prueba": None,
        "permutaciones": 0,
        "historico_corto": n < UMBRAL_HISTORICO_CORTO,
    }
    if n < MIN_MUESTRA:
        return resultado
    media = (n + 1) / 2
    rx = [v - media for v in _rangos(x)]
    ry = [v - media for v in _rangos(y)]
    norma = math.sqrt(sum(v * v for v in rx) * sum(v * v for v in ry))
    if norma == 0:
        resultado["estado"] = "serie_constante"
        return resultado
    producto = sum(a * b for a, b in zip(rx, ry, strict=True))
    exacta = n <= 8
    rng = random.Random(SEMILLA)
    muestras = permutations(rx) if exacta else (rng.sample(rx, n) for _ in range(REPETICIONES))
    extremos = total = 0
    for muestra in muestras:
        # Los rangos medios son múltiplos de 0.5; no se redondea el estadístico.
        simulado = sum(a * b for a, b in zip(muestra, ry, strict=True))
        extremos += abs(simulado) >= abs(producto) - 1e-12
        total += 1
    resultado.update(
        estado="ok",
        rho=max(-1.0, min(1.0, producto / norma)),
        p_valor=extremos / total if exacta else (extremos + 1) / (total + 1),
        prueba="permutacion_exacta" if exacta else "permutacion_monte_carlo",
        permutaciones=total,
    )
    return resultado


def _holm(filas):
    """Ajuste por los índices comparados en un objetivo del ranking."""
    orden = sorted(filas, key=lambda fila: fila["p_valor"])
    previo = 0.0
    for posicion, fila in enumerate(orden):
        previo = max(previo, min(1.0, (len(orden) - posicion) * fila["p_valor"]))
        fila["p_ajustado_holm"] = previo


def analizar_objetivo(objetivos, indices, exclusiones):
    """Mapas temporada→valor; diagnóstico individual y ranking con años comunes."""
    detalles = []
    candidatos = {}
    for nombre, valores in sorted(indices.items()):
        temporadas = sorted(objetivos.keys() & valores.keys())
        medida = correlacion([valores[t] for t in temporadas], [objetivos[t] for t in temporadas])
        motivos = [dict(item) for item in exclusiones.get(nombre, [])]
        motivos.extend(
            {"temporada": t, "motivo": "objetivo_ausente"}
            for t in sorted(valores.keys() - objetivos.keys())
        )
        detalles.append(
            {"indice": nombre, **medida, "temporadas": temporadas, "exclusiones": motivos}
        )
        if medida["estado"] == "ok":
            candidatos[nombre] = valores
    comunes = set(objetivos)
    for valores in candidatos.values():
        comunes.intersection_update(valores)
    temporadas = sorted(comunes) if candidatos else []
    ranking = []
    motivo = None
    if len(candidatos) < 2:
        motivo = "Se necesitan al menos dos índices evaluables para comparar."
    elif len(temporadas) < MIN_MUESTRA:
        motivo = "No hay al menos tres temporadas comunes entre los índices evaluables."
    else:
        for nombre, valores in candidatos.items():
            medida = correlacion(
                [valores[t] for t in temporadas], [objetivos[t] for t in temporadas]
            )
            if medida["estado"] != "ok":
                motivo = "Una serie es constante en las temporadas comunes; no se puede ordenar el conjunto."
                ranking = []
                break
            ranking.append({"indice": nombre, **medida})
        if ranking:
            _holm(ranking)
            ranking.sort(key=lambda fila: (-abs(fila["rho"]), fila["indice"]))
            posicion = 1
            for i, fila in enumerate(ranking):
                if i and not math.isclose(
                    abs(fila["rho"]), abs(ranking[i - 1]["rho"]), abs_tol=1e-12
                ):
                    posicion = i + 1
                fila["posicion"] = posicion
    advertencias = [
        "Análisis exploratorio: asociación no implica causalidad ni capacidad predictiva.",
        "Los p-valores suponen temporadas independientes e intercambiables; tendencias temporales pueden invalidarlos.",
        "La primera posición expresa mayor |rho| observado; no demuestra superioridad estadística entre índices.",
        "Los índices de temporada completa pueden incluir clima posterior a la cosecha; no sirven aquí como pronóstico previo.",
    ]
    if len(temporadas) < UMBRAL_HISTORICO_CORTO or any(d["historico_corto"] for d in detalles):
        advertencias.append(
            "Histórico corto: menos de 10 temporadas útiles. Resultados inestables; revisar con el enólogo."
        )
    return {
        "diagnostico_por_indice": detalles,
        "ranking": ranking,
        "temporadas_comunes": temporadas,
        "n_comun": len(temporadas),
        "motivo_sin_ranking": motivo,
        "advertencias": advertencias,
    }
