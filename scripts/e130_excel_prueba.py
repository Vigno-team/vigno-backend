"""Genera archivos sintéticos para la demo E1C-130; no modifica la base de datos."""

import argparse
from pathlib import Path

from openpyxl import Workbook


def crear(ruta, filas, cabeceras=True):
    libro = Workbook()
    hoja = libro.active
    hoja.title = "mensual"
    for _ in range(4):
        hoja.append([f"Prueba E1C-130, datos sintéticos, año {ruta.stem[-4:]}"])
    if cabeceras:
        hoja.append(
            [
                "FECHA",
                "TEMPERATURA",
                "TEMPERATURA",
                "TEMPERATURA",
                "PP",
                "HUMEDAD RELATIVA",
                "RAD MAX",
                "VEL. MAX. VIENTO",
            ]
        )
        hoja.append(
            [None, "Media diaria", "Máxima", "Mínima", "(mm)", "H.R. Media (%)", "(W/m2)", "(m/s)"]
        )
    else:
        hoja.append(["columna ajena"])
        hoja.append(["otra columna"])
    hoja.append([])
    for fila in filas:
        hoja.append([*fila, 50, 800, 5])
    libro.save(ruta)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("salida", type=Path)
    ruta = parser.parse_args().salida
    ruta.mkdir(parents=True, exist_ok=True)
    filas = [["2025-01-10", 19, 25, 10, 0], ["2025-01-11", 20, 26, 11, 0]]
    crear(ruta / "valido_2025.xlsx", filas)
    crear(
        ruta / "fallas_2024.xlsx",
        [
            [None, 15, 25, 10, 0],
            ["2024-10-10", "mal escrito", 25, 10, 0],
            ["2024-10-11", 80, 26, 11, 0],
            ["2024-10-12", 20, 26, 11, 0],
            *[[f"2024-10-{dia:02d}", 20, 26, 11, 0] for dia in range(13, 32)],
        ],
    )
    crear(
        ruta / "blancos_2025.xlsx",
        [["2025-01-10", None, 25, 10, 0], ["2025-01-11", 20, 26, 11, 0]],
    )
    crear(ruta / "temperaturas_vacias_2025.xlsx", [["2025-01-10", None, None, None, 1]])
    crear(ruta / "columnas_2025.xlsx", filas, cabeceras=False)
    (ruta / "danado_2025.xlsx").write_bytes(b"Esto no es un Excel")
    (ruta / "archivo.pdf").write_bytes(b"%PDF-1.4\nPrueba de extension")
    print(f"Archivos sintéticos creados en {ruta}")


if __name__ == "__main__":
    main()
