import pandas as pd
from django.core.management.base import BaseCommand

from apps.clima.models import MedicionHoraria
from apps.clima.services import VARIABLES_RESUMEN, derivar_resumenes_diarios


class Command(BaseCommand):
    help = "Genera resúmenes diarios pivoteando MedicionHoraria a formato ancho"

    def add_arguments(self, parser):
        parser.add_argument("--estacion", type=str, required=False, help="Nombre de la estación")

    def handle(self, *args, **options):
        # Se conservan las filas excluidas para reemplazar los resúmenes anteriores
        # por null; sus valores se enmascaran antes de agregar.
        qs = MedicionHoraria.objects.filter(variable__in=VARIABLES_RESUMEN)

        if options["estacion"]:
            qs = qs.filter(estacion__nombre=options["estacion"])

        if not qs.exists():
            self.stdout.write(self.style.WARNING("No hay datos en MedicionHoraria para procesar."))
            return

        df = pd.DataFrame(
            qs.values(
                "estacion_id",
                "timestamp",
                "frecuencia",
                "variable",
                "valor",
                "motivo_nulo",
                "fuera_de_rango",
                "excluido",
                "origen",
            )
        )

        claves = ["estacion_id", "timestamp", "frecuencia"]
        valores = df.set_index(claves + ["variable"])["valor"].unstack("variable")
        motivos = df.groupby(claves)["motivo_nulo"].first()
        marcas = df.set_index(claves + ["variable"])["fuera_de_rango"].unstack("variable")
        marcas = marcas.add_suffix("_fuera_de_rango")
        exclusiones = df.set_index(claves + ["variable"])["excluido"].unstack("variable")
        exclusiones = exclusiones.add_suffix("_excluido")
        manual = (
            df.assign(origen_manual=df["origen"].eq("manual") & ~df["excluido"])
            .groupby(claves)["origen_manual"]
            .any()
        )
        ancho = valores.join(motivos).join(marcas).join(exclusiones).join(manual).reset_index()
        ancho.columns.name = None

        registros = derivar_resumenes_diarios(ancho)
        self.stdout.write(self.style.SUCCESS(f"Generados {len(registros)} resúmenes diarios."))
