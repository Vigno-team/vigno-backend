import pandas as pd
from django.core.management.base import BaseCommand

from apps.clima.models import MedicionHoraria
from apps.clima.services import derivar_resumenes_diarios


class Command(BaseCommand):
    help = "Genera resúmenes diarios pivoteando MedicionHoraria a formato ancho"

    def add_arguments(self, parser):
        parser.add_argument("--estacion", type=str, required=False, help="Nombre de la estación")

    def handle(self, *args, **options):
        qs = MedicionHoraria.objects.filter(
            variable__in=[
                "temperatura_maxima",
                "temperatura_minima",
                "temperatura_media",
                "precipitacion",
            ]
        )

        if options["estacion"]:
            qs = qs.filter(estacion__nombre=options["estacion"])

        if not qs.exists():
            self.stdout.write(self.style.WARNING("No hay datos en MedicionHoraria para procesar."))
            return

        df = pd.DataFrame(
            qs.values("estacion_id", "timestamp", "frecuencia", "variable", "valor", "motivo_nulo")
        )

        ancho = df.pivot_table(
            index=["estacion_id", "timestamp", "frecuencia"],
            columns="variable",
            values="valor",
            aggfunc="first",
            dropna=False,
        ).reset_index()

        registros = derivar_resumenes_diarios(ancho)
        self.stdout.write(self.style.SUCCESS(f"Generados {len(registros)} resúmenes diarios."))
