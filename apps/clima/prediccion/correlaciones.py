"""Spearman con p por permutaciones y ajuste de Holm (traído de archivo/e1c-20)."""

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
    """Ajuste de Holm sobre las filas que se comparan juntas; escribe p_ajustado_holm en cada una."""
    orden = sorted(filas, key=lambda fila: fila["p_valor"])
    previo = 0.0
    for posicion, fila in enumerate(orden):
        previo = max(previo, min(1.0, (len(orden) - posicion) * fila["p_valor"]))
        fila["p_ajustado_holm"] = previo
