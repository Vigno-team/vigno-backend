import os

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.clima.prediccion.analisis_madurez import correlacionar_clima_madurez


class Command(BaseCommand):
    help = "Correlaciona indices climaticos con fecha de cosecha y madurez"

    def handle(self, *args, **options):
        ruta = os.path.join(settings.BASE_DIR, "data", "ficticio", "cosechas.csv")
        if not os.path.exists(ruta):
            self.stdout.write(self.style.ERROR("Error: Falta cosechas.csv"))
            return

        resultados = correlacionar_clima_madurez(ruta)

        self.stdout.write("--- Correlaciones Destacadas ---")
        for r in resultados:
            if r["indice"] == "winkler" and r["objetivo"] == "doy":
                # Criterio de aceptación: Winkler vs Doy debe dar negativo
                color = self.style.SUCCESS if r["rho"] < 0 else self.style.WARNING
                self.stdout.write(
                    color(
                        f"[{r['nivel']}] {r['indice']} vs {r['objetivo']} -> rho: {r['rho']}, p_holm: {r['p_holm']} (n={r['n']})"
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"¡Éxito! {len(resultados)} correlaciones calculadas con formato listo para el JSON."
            )
        )
