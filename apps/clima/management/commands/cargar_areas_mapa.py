from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.clima.areas_mapa import AreasMapaError, cargar_areas
from apps.clima.models import Estacion


class Command(BaseCommand):
    help = (
        "Valida config/areas_mapa.json y copia latitud y longitud de cada estación a la base. "
        "Es idempotente: se puede correr las veces que haga falta."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--archivo",
            default=str(settings.BASE_DIR / "config" / "areas_mapa.json"),
            help="Ruta del GeoJSON (por defecto config/areas_mapa.json).",
        )
        parser.add_argument(
            "--solo-validar",
            action="store_true",
            help="Valida el archivo y muestra los cambios, sin escribir en la base.",
        )

    def handle(self, *args, **options):
        try:
            areas = cargar_areas(Path(options["archivo"]))
        except AreasMapaError as exc:
            raise CommandError(str(exc)) from exc

        por_codigo = {e.codigo: e for e in Estacion.objects.exclude(codigo__isnull=True)}
        desconocidos = [a.codigo for a in areas if a.codigo not in por_codigo]
        if desconocidos:
            raise CommandError(
                f"Códigos sin estación en la base: {', '.join(desconocidos)}. "
                f"Existentes: {', '.join(sorted(por_codigo)) or 'ninguno'}."
            )
        sin_area = sorted(set(por_codigo) - {a.codigo for a in areas})
        if sin_area:
            self.stdout.write(
                self.style.WARNING(f"Estaciones sin contorno en el archivo: {', '.join(sin_area)}.")
            )

        with transaction.atomic():
            for area in areas:
                estacion = por_codigo[area.codigo]
                self.stdout.write(
                    f"{area.codigo}: latitud {estacion.latitud} -> {area.latitud}, "
                    f"longitud {estacion.longitud} -> {area.longitud}"
                )
                if not area.estacion_dentro:
                    self.stdout.write(
                        self.style.WARNING(
                            f"  Aviso: la estación {area.codigo} queda fuera de su contorno."
                        )
                    )
                if not options["solo_validar"]:
                    estacion.latitud = area.latitud
                    estacion.longitud = area.longitud
                    estacion.save(update_fields=["latitud", "longitud"])

        accion = "Validado (sin escribir)" if options["solo_validar"] else "Actualizadas"
        self.stdout.write(self.style.SUCCESS(f"{accion}: {len(areas)} estación(es)."))
