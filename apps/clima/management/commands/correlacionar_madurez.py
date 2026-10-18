from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.clima.prediccion.analisis_madurez import correlacionar_clima_madurez


class Command(BaseCommand):
    help = "Correlaciona índices climáticos con fecha de cosecha y madurez (E1C-82)"

    def handle(self, *args, **options):
        ruta = settings.BASE_DIR / "data" / "ficticio" / "cosechas.csv"
        if not ruta.exists():
            raise CommandError("Falta cosechas.csv: corre primero cargar_dataset_ficticio")

        resultados = correlacionar_clima_madurez(ruta)
        for r in resultados:
            if r["indice"] == "winkler" and r["objetivo"] == "doy":
                # Criterio de E1C-82: Winkler vs. día de cosecha debe salir negativo.
                estilo = self.style.SUCCESS if r["rho"] < 0 else self.style.WARNING
                self.stdout.write(
                    estilo(
                        f"[{r['nivel']}] winkler vs doy: rho={r['rho']}, p_holm={r['p_holm']}, n={r['n']}"
                    )
                )
        self.stdout.write(
            self.style.SUCCESS(f"¡Éxito! {len(resultados)} correlaciones calculadas.")
        )
