from django.core.management.base import BaseCommand

from apps.clima.indices import calcular_indices_temporada
from apps.clima.models import Estacion, ResumenDiario


class Command(BaseCommand):
    help = "Calcula los índices de Winkler y Huglin para todas las temporadas disponibles"

    def add_arguments(self, parser):
        parser.add_argument(
            "--estacion", type=str, help="Nombre de la estación específica a calcular"
        )

    def handle(self, *args, **options):
        nombre_estacion = options.get("estacion")

        if nombre_estacion:
            estaciones = Estacion.objects.filter(nombre=nombre_estacion)
        else:
            estaciones = Estacion.objects.all()

        for estacion in estaciones:
            temporadas = set(
                ResumenDiario.objects.filter(estacion=estacion).values_list("temporada", flat=True)
            )

            for temporada in temporadas:
                if not temporada:
                    continue
                self.stdout.write(
                    f"Calculando índices para {estacion.nombre}, temporada {temporada}..."
                )
                calcular_indices_temporada(estacion, temporada)
                self.stdout.write(self.style.SUCCESS("  OK"))
