from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.clima.prediccion.dataset import procesar_historico_ficticio


class Command(BaseCommand):
    help = "Une los 3 Excel del dataset de California en data/ficticio/cosechas.csv"

    def handle(self, *args, **options):
        carpeta = settings.BASE_DIR / "data" / "ficticio"
        rutas = [carpeta / f"Subset{i}.xlsx" for i in (1, 2, 3)]
        faltan = [r.name for r in rutas if not r.exists()]
        if faltan:
            raise CommandError(f"Faltan {', '.join(faltan)} en data/ficticio/")

        salida = carpeta / "cosechas.csv"
        try:
            df = procesar_historico_ficticio(*rutas, salida)
        except ValueError as error:
            raise CommandError(str(error)) from error

        amerine = df[df["fuente"] == "Amerine & Winkler"]
        promedios = amerine.groupby("region")["doy"].mean().round(0).to_dict()
        self.stdout.write(self.style.SUCCESS(f"¡Éxito! CSV generado en {salida}"))
        self.stdout.write(f"Filas Subset1: {len(amerine)} (esperado: 1473)")
        self.stdout.write(
            f"Día de cosecha promedio por región: {promedios} (esperado ~280, 273, 266, 269, 243)"
        )
