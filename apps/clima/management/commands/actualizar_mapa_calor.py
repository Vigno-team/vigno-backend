from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.clima.areas_mapa import AreasMapaError, cargar_geometria_predio
from apps.clima.models import Estacion
from apps.clima.satelite import ErrorSatelite, actualizar_capa_ndvi


class Command(BaseCommand):
    help = "Actualiza manualmente una capa satelital de un predio."

    def add_arguments(self, parser):
        parser.add_argument("--estacion", required=True, help="Código de estación/predio.")
        parser.add_argument("--capa", required=True, choices=("ndvi",), help="Capa a actualizar.")

    def handle(self, *args, **options):
        codigo = options["estacion"]
        capa = options["capa"]
        try:
            estacion = Estacion.objects.get(codigo=codigo)
        except Estacion.DoesNotExist as exc:
            raise CommandError(f"No existe la estación {codigo}.") from exc

        ruta_areas = settings.BASE_DIR / "config" / "areas_mapa.json"
        try:
            geometria = cargar_geometria_predio(ruta_areas, codigo)
        except AreasMapaError as exc:
            raise CommandError(str(exc)) from exc

        if capa != "ndvi":
            raise CommandError(f"Capa no soportada: {capa}.")
        try:
            resultado = actualizar_capa_ndvi(estacion, geometria)
        except ErrorSatelite as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"{codigo} NDVI {resultado.fecha_imagen}: "
                f"{resultado.ancho}x{resultado.alto}, "
                f"{resultado.porcentaje_validos:.1f}% válido, "
                f"{resultado.nubosidad_pct:.1f}% de nubosidad."
            )
        )
