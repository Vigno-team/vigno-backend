import json
from datetime import UTC, datetime

import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Evalúa modelos en años de California no usados para entrenar y exporta métricas."

    def add_arguments(self, parser):
        parser.add_argument("--anios-prueba", type=int, nargs="+", default=[1941])

    def handle(self, *args, **options):
        ruta_datos = settings.BASE_DIR / "data" / "ficticio" / "cosechas.csv"
        ruta_json = ruta_datos.with_name("prediccion_cosecha_california.json")
        if not ruta_datos.is_file():
            raise CommandError(f"No se encontró el dataset en {ruta_datos}")
        try:
            import joblib

            from apps.clima.prediccion.modelo import evaluar_por_anio
        except ImportError as error:
            raise CommandError(
                "Instala requirements-ml.txt para ejecutar entrenar_cosecha"
            ) from error
        try:
            datos = pd.read_csv(ruta_datos)
            if datos.empty:
                raise ValueError("El CSV no tiene filas")
            resultado, modelos = evaluar_por_anio(datos, options["anios_prueba"])
        except (ValueError, OSError) as error:
            raise CommandError(str(error)) from error

        version = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        ruta_modelo = settings.BASE_DIR / "apps" / "ml" / "artifacts" / f"cosecha_{version}.joblib"
        resultado["version_modelo"] = version
        try:
            ruta_modelo.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump(
                {
                    "modelos": modelos,
                    "version": version,
                    "features": resultado["features"],
                    "validacion": resultado["validacion"],
                    "fuente": resultado["fuente"],
                },
                ruta_modelo,
            )
            ruta_json.write_text(
                json.dumps(resultado, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
                encoding="utf-8",
            )
        except (OSError, ValueError) as error:
            raise CommandError(f"No se pudo guardar la evaluación: {error}") from error
        validacion = resultado["validacion"]
        self.stdout.write(f"Años de entrenamiento: {validacion['anios_entrenamiento']}")
        self.stdout.write(f"Años de prueba: {validacion['anios_prueba']}")
        self.stdout.write(f"Filas de prueba: {validacion['filas_prueba']}")
        for nombre, metricas in resultado["metricas"].items():
            self.stdout.write(
                f"{nombre}: MAE={metricas['mae_dias']:.4f} días; RMSE={metricas['rmse_dias']:.4f} días"
            )
        self.stdout.write(self.style.SUCCESS(f"Evaluación exportada en {ruta_json}"))
        self.stdout.write(f"Modelos versionados en {ruta_modelo}")
