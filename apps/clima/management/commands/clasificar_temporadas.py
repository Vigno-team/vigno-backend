import os

from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Clasifica la calidad de las temporadas del dataset ficticio"

    def handle(self, *args, **options):
        base_dir = settings.BASE_DIR
        ruta_entrada = os.path.join(base_dir, "data", "ficticio", "cosechas.csv")
        ruta_salida = os.path.join(base_dir, "data", "ficticio", "cosechas_clasificadas.csv")

        try:
            self.stdout.write("Evaluando calidad de las cosechas...")
            df = procesar_calidad_temporadas(ruta_entrada, ruta_salida)

            conteo = df["calidad_estimada"].value_counts().to_dict()

            self.stdout.write(
                self.style.SUCCESS(f"¡Éxito! Dataset clasificado generado en {ruta_salida}")
            )
            self.stdout.write(f"Resumen de calidades: {conteo}")

        except FileNotFoundError:
            self.stdout.write(
                self.style.ERROR(
                    "Error: Primero debes generar el cosechas.csv ejecutando cargar_dataset_ficticio"
                )
            )
