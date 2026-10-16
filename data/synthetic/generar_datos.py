import argparse
import csv
import math
import random
from datetime import date, timedelta
from pathlib import Path

# ¡No cambiar sin regenerar la referencia del test.!
SEMILLA = 20261010

# Nombres de variable canónicos, los mismos que usa MedicionHoraria.variable.
VARIABLES = ("temperatura_maxima", "temperatura_minima", "temperatura_media", "precipitacion")

# Mismo texto que escribe ingestar_excel cuando la celda viene vacía.
MOTIVO_NULO = "Dato en blanco en origen"


def _rango(inicio: date, fin: date) -> set[date]:
    return {inicio + timedelta(days=i) for i in range((fin - inicio).days + 1)}


# Cada estación define su escenario. Los casos borde son explícitos (no aleatorios) para que
# cubrirlos no dependa de la suerte de la semilla.
ESTACIONES = (
    {
        "nombre": "Sintética Norte",
        "codigo": "sint-norte-01",
        "subzona": "sintetica-norte",
        "propietario": "Datos sintéticos",
        "latitud": -35.52,
        # 4 temporadas completas: 2021-2022 a 2024-2025.
        "desde": date(2021, 7, 1),
        "hasta": date(2025, 6, 30),
        "ajuste_temp_c": 0.0,
        "prob_dia_sin_dato": 0.02,
        # Días sin fila alguna (la estación no registró nada).
        "dias_sin_fila": set(),
        # Días con fila pero todos los valores nulos, además de los aleatorios.
        "dias_sin_dato": {date(2024, 1, 24)},
        # Días con temperatura pero sin precipitación.
        "dias_sin_lluvia": set(),
        # Olas de calor: (inicio, largo en días), con tmax entre 36,0 y 38,4 °C.
        # 2022: racha de 7 días (con incidencia). 2023: racha corta de 3 (sin incidencia).
        # 2024: ola del 18 al 29 de enero cortada por el día sin dato del 24: quedan dos rachas
        # de 6 y 5 días, ambas con incidencia y marcadas como interrumpidas por dato faltante.
        # 2025: racha de 6 días. Los días sin dato aleatorios nunca caen dentro de una ola.
        "olas_calor": (
            (date(2022, 1, 10), 7),
            (date(2023, 1, 5), 3),
            (date(2024, 1, 18), 12),
            (date(2025, 2, 1), 6),
        ),
    },
    {
        "nombre": "Sintética Sur",
        "codigo": "sint-sur-01",
        "subzona": "sintetica-sur",
        "propietario": "Datos sintéticos",
        # Sin latitud: el índice de Huglin no puede ser confiable.
        "latitud": None,
        # Parte en mayo de 2022: la temporada 2021-2022 queda solo con mayo-junio (sin verano).
        "desde": date(2022, 5, 1),
        "hasta": date(2025, 6, 30),
        "ajuste_temp_c": -1.2,
        "prob_dia_sin_dato": 0.0,
        # Hueco de 55 días en el verano 2023-2024: el Winkler de esa temporada no es confiable.
        "dias_sin_fila": _rango(date(2023, 12, 5), date(2024, 1, 28)),
        "dias_sin_dato": set(),
        # 20 días de junio de 2024 sin precipitación, aunque con temperatura.
        "dias_sin_lluvia": _rango(date(2024, 6, 1), date(2024, 6, 20)),
        "olas_calor": ((date(2023, 1, 15), 5), (date(2025, 1, 12), 4)),
    },
)


def _estacional(fecha: date) -> float:
    """1 a mediados de enero (pleno verano austral) y -1 a mediados de julio."""
    dia = fecha.timetuple().tm_yday
    return round(math.cos(2 * math.pi * (dia - 15) / 365.25), 6)


def _temporada_inicio(fecha: date) -> int:
    return fecha.year if fecha.month >= 7 else fecha.year - 1


def _generar_estacion(est: dict) -> list[dict]:
    rng = random.Random(f"{SEMILLA}-{est['codigo']}")

    # Un valor por temporada (anomalía térmica) y por año calendario (factor de lluvia), sorteados
    # por adelantado y en orden, para que las temporadas se distingan entre sí.
    anios = range(est["desde"].year - 1, est["hasta"].year + 2)
    anomalia_temp = {a: rng.uniform(-1.2, 1.2) for a in anios}
    factor_lluvia = {a: rng.choice((0.5, 0.8, 1.0, 1.3, 1.7)) for a in anios}

    dias_ola = set()
    for inicio, largo in est["olas_calor"]:
        dias_ola |= _rango(inicio, inicio + timedelta(days=largo - 1))

    filas = []
    fecha = est["desde"]
    while fecha <= est["hasta"]:
        # Se sortean SIEMPRE los mismos valores por día, aunque luego no se usen: así agregar un
        # hueco o un día sin dato no desplaza los números de los días siguientes.
        ruido_tmax = rng.gauss(0, 2.2)
        ruido_amp = rng.gauss(0, 1.5)
        ruido_media = rng.gauss(0, 0.3)
        sorteo_lluvia = rng.random()
        monto_lluvia = rng.expovariate(1 / 9.0)
        sorteo_sin_dato = rng.random()

        if fecha not in est["dias_sin_fila"]:
            est_f = _estacional(fecha)
            base = (
                14.5 + 7.5 * est_f + est["ajuste_temp_c"] + anomalia_temp[_temporada_inicio(fecha)]
            )
            amplitud = max(6.0, 14.0 + 3.0 * est_f + ruido_amp)
            tmax = base + amplitud / 2 + ruido_tmax
            tmin = base - amplitud / 2 + ruido_tmax * 0.5
            if fecha in dias_ola:
                tmax = 36.0 + 0.6 * (fecha.toordinal() % 5)
                tmin = min(tmin, tmax - 8.0)
            tmedia = min(max((tmax + tmin) / 2 + ruido_media, tmin), tmax)

            p_lluvia = 0.04 + 0.30 * max(0.0, -est_f)
            lluvia = 0.0
            if sorteo_lluvia < p_lluvia:
                lluvia = max(0.2, monto_lluvia * factor_lluvia[fecha.year])

            fila = {
                "estacion": est["codigo"],
                "fecha": fecha,
                "temperatura_maxima": round(tmax, 1),
                "temperatura_minima": round(tmin, 1),
                "temperatura_media": round(tmedia, 1),
                "precipitacion": round(lluvia, 1),
            }
            if fecha in est["dias_sin_lluvia"]:
                fila["precipitacion"] = None
            al_azar = sorteo_sin_dato < est["prob_dia_sin_dato"] and fecha not in dias_ola
            if fecha in est["dias_sin_dato"] or al_azar:
                fila.update(dict.fromkeys(VARIABLES))
            filas.append(fila)
        fecha += timedelta(days=1)
    return filas


def generar() -> list[dict]:
    """Todas las filas diarias de todas las estaciones, ordenadas por estación y fecha.

    Cada fila: estacion (código), fecha (date) y las cuatro VARIABLES (float o None).
    Un día sin fila es un día en que la estación no registró nada.
    """
    filas = []
    for est in ESTACIONES:
        filas.extend(_generar_estacion(est))
    return filas


def escribir_csv(salida: Path) -> int:
    filas = generar()
    salida.parent.mkdir(parents=True, exist_ok=True)
    with salida.open("w", encoding="utf-8", newline="") as archivo:
        escritor = csv.writer(archivo, lineterminator="\n")
        escritor.writerow(["estacion", "fecha", *VARIABLES])
        for f in filas:
            escritor.writerow(
                [f["estacion"], f["fecha"].isoformat()]
                + ["" if f[v] is None else f[v] for v in VARIABLES]
            )
    return len(filas)


def main():
    parser = argparse.ArgumentParser(description="Genera los datos sintéticos de E1C-105.")
    parser.add_argument(
        "--salida",
        default="data/synthetic/datos_sinteticos.csv",
        help="CSV de salida (solo para inspeccionar los datos; el test no lo usa).",
    )
    args = parser.parse_args()
    n = escribir_csv(Path(args.salida))
    print(f"{args.salida}: {n} filas diarias de {len(ESTACIONES)} estaciones")


if __name__ == "__main__":
    main()
