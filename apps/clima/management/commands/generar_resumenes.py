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

        claves = ["estacion_id", "timestamp", "frecuencia"]
        valores = df.set_index(claves + ["variable"])["valor"].unstack("variable")
        motivos = df.groupby(claves)["motivo_nulo"].first()
        ancho = valores.join(motivos).reset_index()
        ancho.columns.name = None

        registros = derivar_resumenes_diarios(ancho)
        self.stdout.write(self.style.SUCCESS(f"Generados {len(registros)} resúmenes diarios."))
