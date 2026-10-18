import os

import pandas as pd

RUTA = "data/raw"

resultado = []


if not os.path.exists(RUTA):
    print("No existe la carpeta data/raw")
    exit()


for archivo in os.listdir(RUTA):
    if archivo.endswith(".xlsx"):
        ruta_archivo = os.path.join(RUTA, archivo)

        print(f"Analizando: {archivo}")

        excel = pd.ExcelFile(ruta_archivo)

        for hoja in excel.sheet_names:
            df = pd.read_excel(ruta_archivo, sheet_name=hoja)

            resultado.append(
                {
                    "archivo": archivo,
                    "hoja": hoja,
                    "filas": len(df),
                    "columnas": len(df.columns),
                    "columnas_detectadas": ", ".join(df.columns.astype(str)),
                }
            )


inventario = pd.DataFrame(resultado)


inventario.to_excel("output/inventario_excel.xlsx", index=False)


print("Inventario generado correctamente")
