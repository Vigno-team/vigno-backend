from django.core.management.base import BaseCommand

from apps.clima.models import MedicionHoraria
from apps.clima.rangos import VARIABLES, cargar_rangos, motivo_fuera_de_rango


class Command(BaseCommand):
    help = "Marca el histórico con el catálogo actual sin modificar los valores originales."

    def add_arguments(self, parser):
        parser.add_argument("--estacion", help="Nombre de estación; por defecto todas")

    def handle(self, *args, **options):
        catalogo = cargar_rangos()
        qs = MedicionHoraria.objects.filter(variable__in=VARIABLES).order_by("pk")
        if options["estacion"]:
            qs = qs.filter(estacion__nombre=options["estacion"])
        lote = []
        actualizadas = 0
        for medicion in qs.iterator(chunk_size=1000):
            motivo = motivo_fuera_de_rango(
                medicion.variable, medicion.valor, medicion.frecuencia, catalogo
            )
            if (medicion.fuera_de_rango, medicion.motivo_fuera_de_rango) == (bool(motivo), motivo):
                continue
            medicion.fuera_de_rango = bool(motivo)
            medicion.motivo_fuera_de_rango = motivo
            lote.append(medicion)
            actualizadas += 1
            if len(lote) == 1000:
                MedicionHoraria.objects.bulk_update(
                    lote, ["fuera_de_rango", "motivo_fuera_de_rango"]
                )
                lote.clear()
        if lote:
            MedicionHoraria.objects.bulk_update(lote, ["fuera_de_rango", "motivo_fuera_de_rango"])
        self.stdout.write(
            f"Marcas actualizadas: {actualizadas}. Ejecuta generar_resumenes y recalcula los índices."
        )
