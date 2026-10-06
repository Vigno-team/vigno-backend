import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.clima.analisis_cosecha import generar_informe
from apps.clima.models import Estacion


class Command(BaseCommand):
    help = (
        "E1C-20: correlaciona índices reales con un histórico D1.3 y exporta un JSON exploratorio."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--historico", required=True, help="Archivo JSON con el contrato documentado."
        )
        parser.add_argument(
            "--estacion", required=True, help="Código exacto de la estación representativa."
        )
        parser.add_argument("--cepa", required=True, help="Nombre exacto de la cepa del histórico.")
        parser.add_argument(
            "--salida", required=True, help="Archivo JSON nuevo; no sobrescribe archivos."
        )

    def handle(self, *args, **options):
        entrada = Path(options["historico"])
        salida = Path(options["salida"])
        try:
            documento = json.loads(entrada.read_text(encoding="utf-8-sig"))
            estacion = Estacion.objects.get(codigo=options["estacion"])
            informe = generar_informe(documento, estacion, options["cepa"])
            contenido = json.dumps(informe, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
            # El informe contiene datos del cliente: usar data/cliente (ignorado por Git).
            salida.parent.mkdir(parents=True, exist_ok=True)
            with salida.open("x", encoding="utf-8") as archivo:
                archivo.write(contenido)
        except Estacion.DoesNotExist as exc:
            raise CommandError("No existe una estación con ese código.") from exc
        except (OSError, ValueError, TypeError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"Informe exploratorio generado: {salida}"))
        for objetivo, resultado in informe["resultados"].items():
            self.stdout.write(
                f"{objetivo}: n común={resultado['n_comun']}; índices en ranking={len(resultado['ranking'])}"
            )
            for aviso in resultado["advertencias"]:
                self.stdout.write(self.style.WARNING(aviso))
