import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.clima.prediccion.calidad_vino import calidad_por_temporada


class Command(BaseCommand):
    help = "Calcula la calidad por temporada del dataset ficticio (E1C-79)"

    def handle(self, *args, **options):
        carpeta = settings.BASE_DIR / "data" / "ficticio"
        entrada = carpeta / "cosechas.csv"
        if not entrada.exists():
            raise CommandError("Falta cosechas.csv: corre primero cargar_dataset_ficticio")

        try:
            calidad = calidad_por_temporada(pd.read_csv(entrada))
        except ValueError as error:
            raise CommandError(str(error)) from error

        salida = carpeta / "calidad_temporadas.csv"
        calidad.to_csv(salida, index=False, encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"¡Éxito! {len(calidad)} temporadas en {salida}"))
