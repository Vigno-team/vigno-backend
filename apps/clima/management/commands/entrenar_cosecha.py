import json
import os
from datetime import datetime

import joblib
import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand

from apps.clima.prediccion.modelo import (
    FEATURES_PERMITIDAS,
    entrenar_modelos,
    extraer_justificacion,
    predecir_ventana,
    preparar_datos,
)


class Command(BaseCommand):
    help = "Entrena el modelo de ventana de cosecha con datos ficticios y genera el JSON para el frontend."

    def handle(self, *args, **options):
        # Definir rutas
        ruta_datos = settings.BASE_DIR / "data" / "ficticio" / "cosechas.csv"
        dir_artefactos = settings.BASE_DIR / "apps" / "ml" / "artifacts"
        ruta_json = settings.BASE_DIR / "data" / "ficticio" / "prediccion_cosecha_vigno.json"

        os.makedirs(dir_artefactos, exist_ok=True)

        # Cargar datos
        if not ruta_datos.exists():
            self.stdout.write(self.style.ERROR(f"No se encontró el dataset en {ruta_datos}"))
            return

        df = pd.read_csv(ruta_datos)

        # Preparar features y entrenar
        X, y = preparar_datos(df)
        if X.empty:
            self.stdout.write(self.style.ERROR("No hay datos válidos para entrenar."))
            return

        modelo_rf, modelo_lr = entrenar_modelos(X, y)

        # Versionar y guardar el artefacto
        fecha_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        ruta_modelo = dir_artefactos / f"rf_cosecha_{fecha_str}.joblib"

        metadatos = {
            "modelo": modelo_rf,
            "features": FEATURES_PERMITIDAS,
            "fecha_entrenamiento": fecha_str,
        }
        joblib.dump(metadatos, ruta_modelo)
        self.stdout.write(self.style.SUCCESS(f"Modelo versionado y guardado en {ruta_modelo}"))

        # Generar predicciones y contrato JSON (iterando sobre las últimas 10 temporadas como prueba)
        resultados = []
        justificacion = extraer_justificacion(modelo_rf)

        # Simula que queremos predecir la ventana para los registros más recientes
        df_prediccion = df.dropna(
            subset=["gst", "wi", "hi", "region", "color", "doy"]
        ).tail(10).copy()
        
        for _, row in df_prediccion.iterrows():
            df_fila = pd.DataFrame([row])
            X_in, _ = preparar_datos(df_fila)

            if X_in.empty:
                continue

            # Determinamos el año de cosecha (si no viene, se asume el actual para proyectar la fecha)
            anho_cosecha = int(row.get("anho_cosecha", datetime.now().year))
            ventana = predecir_ventana(modelo_rf, X_in, anho_cosecha)

            resultados.append({
                "temporada": str(row.get("temporada", f"{anho_cosecha-1}-{anho_cosecha}")),
                "subzona": str(row.get("subzona", "Cauquenes")),
                "cepa": str(row.get("cepa", "Cabernet Sauvignon")),
                "color": str(row.get("color", "tinto")),
                "region_winkler": str(row.get("region", "IV")),
                "prediccion": ventana,
                "datos_entrada": {
                    "GST": float(row["gst"]),
                    "Winkler": float(row["wi"]),
                    "Huglin": float(row["hi"]),
                    "region": str(row["region"]),
                    "color": str(row["color"]),
                },
                "justificacion": justificacion,
            })

        # Guardar el JSON del contrato
        with open(ruta_json, "w", encoding="utf-8") as f:
            json.dump(resultados, f, indent=2, ensure_ascii=False)

        self.stdout.write(self.style.SUCCESS(f"Contrato JSON exportado exitosamente en {ruta_json}"))