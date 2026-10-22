"""E1C-124: adapta la evaluación de E1C-85 al contrato del frontend."""

import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.clima.archivos import escribir_json_atomico


def _rechazar_no_finito(valor):
    raise ValueError(f"El JSON contiene un número no finito: {valor}")


def construir_payload(evaluacion):
    if not isinstance(evaluacion, dict):
        raise ValueError("La evaluación debe ser un objeto JSON")
    requeridos = {
        "datos_ficticios",
        "fuente",
        "dataset_url",
        "version_modelo",
        "features",
        "importancias_random_forest",
        "regresion_lineal",
        "metricas",
        "comparacion_base",
        "validacion",
        "predicciones",
    }
    faltan = requeridos - evaluacion.keys()
    if faltan:
        raise ValueError(f"Faltan campos de E1C-85: {', '.join(sorted(faltan))}")
    if evaluacion["datos_ficticios"] is not True:
        raise ValueError("La entrada debe estar marcada como datos_ficticios: true")
    for campo in (
        "importancias_random_forest",
        "regresion_lineal",
        "metricas",
        "comparacion_base",
        "validacion",
    ):
        if not isinstance(evaluacion[campo], dict) or not evaluacion[campo]:
            raise ValueError(f"{campo} debe ser un objeto no vacío")
    for campo in ("features", "predicciones"):
        if not isinstance(evaluacion[campo], list) or not evaluacion[campo]:
            raise ValueError(f"{campo} debe ser una lista no vacía")
    campos_fila = {
        "fuente",
        "region",
        "anio",
        "cultivar",
        "color",
        "doy_real",
        "doy_estimado",
        "diferencia_dias",
        "fecha_real",
        "prediccion",
    }
    for fila in evaluacion["predicciones"]:
        if not isinstance(fila, dict) or not campos_fila.issubset(fila):
            raise ValueError("Cada predicción debe conservar la identidad y resultados de E1C-85")

    return {
        "generado": timezone.now().isoformat(),
        "datos_ficticios": evaluacion["datos_ficticios"],
        "fuente": {"cita": evaluacion["fuente"], "url": evaluacion["dataset_url"]},
        "convencion_fechas": "Fechas originales de California; sin desplazamiento a Chile.",
        "modelo": {
            "version": evaluacion["version_modelo"],
            "variables": evaluacion["features"],
            "importancias": evaluacion["importancias_random_forest"],
            "regresion_lineal": evaluacion["regresion_lineal"],
            "metricas": evaluacion["metricas"],
            "comparacion_base": evaluacion["comparacion_base"],
            "validacion": evaluacion["validacion"],
        },
        "predicciones": evaluacion["predicciones"],
    }


class Command(BaseCommand):
    help = "Exporta al frontend los resultados calculados por entrenar_cosecha (California)."

    def handle(self, *args, **options):
        carpeta = settings.BASE_DIR / "data" / "ficticio"
        entrada = carpeta / "prediccion_cosecha_california.json"
        salida = carpeta / "prediccion_ficticia.json"
        if not entrada.is_file():
            raise CommandError("Corre primero: python manage.py entrenar_cosecha")
        try:
            evaluacion = json.loads(
                entrada.read_text(encoding="utf-8"), parse_constant=_rechazar_no_finito
            )
            escribir_json_atomico(salida, construir_payload(evaluacion))
        except (OSError, ValueError, TypeError) as error:
            raise CommandError(
                f"No se pudo exportar la evaluación de California: {error}"
            ) from error
        self.stdout.write(self.style.SUCCESS(f"Predicciones exportadas en {salida}"))
