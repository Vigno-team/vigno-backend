"""E1C-129: recalcula todo y deja listos los datos del frontend en DATOS_DIR."""

import importlib.util
import json
import logging
import time
from contextlib import contextmanager
from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.models import Max
from django.utils import timezone

from apps.clima.archivos import escribir_json_atomico
from apps.clima.models import CapaSatelital, Estacion

logger = logging.getLogger(__name__)

# Si fallan estos pasos el frontend quedaría con datos viejos o incompletos.
PASOS_CRITICOS = {"generar_resumenes", "calcular_indices", "clasificar_temporadas", "exportar_json"}
# Sentinel-2 pasa cada ~5 días: antes de eso no hay imagen nueva que pedir.
DIAS_CAPA_VIGENTE = 5
# Clave del pg_advisory_lock; cualquier entero fijo sirve mientras nadie más lo use.
CLAVE_CANDADO = 129_000_129


class Omitido(Exception):
    """El paso no corresponde en esta corrida; no cuenta como fallo."""


@contextmanager
def candado():
    """Si la carga por API y el programador coinciden, el segundo espera al primero."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_lock(%s)", [CLAVE_CANDADO])
    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_unlock(%s)", [CLAVE_CANDADO])


def hay_sklearn() -> bool:
    return importlib.util.find_spec("sklearn") is not None


def estaciones_con_contorno() -> list[str]:
    ruta = settings.BASE_DIR / "config" / "areas_mapa.json"
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    codigos = {
        (feature.get("properties") or {}).get("codigo")
        for feature in datos.get("features", [])
        if feature.get("geometry") is not None
    }
    return list(
        Estacion.objects.filter(codigo__in=codigos)
        .order_by("codigo")
        .values_list("codigo", flat=True)
    )


class Command(BaseCommand):
    help = "Corre todos los pasos del backend y deja el JSON del frontend y actualizacion.json."

    def add_arguments(self, parser):
        satelite = parser.add_mutually_exclusive_group()
        satelite.add_argument(
            "--sin-satelite", action="store_true", help="No pide capas a Copernicus."
        )
        satelite.add_argument(
            "--forzar-satelite",
            action="store_true",
            help="Pide capas aunque la última tenga menos de 5 días.",
        )

    def handle(self, *args, **options):
        with candado():
            pasos = self.correr_pasos(options)
            fallidos = [p["paso"] for p in pasos if not p["ok"] and p["paso"] in PASOS_CRITICOS]
            estado = {
                "generado": timezone.localtime().isoformat(timespec="seconds"),
                "ok": not fallidos,
                "pasos": pasos,
            }
            escribir_json_atomico(settings.DATOS_DIR / "actualizacion.json", estado)

        if fallidos:
            raise CommandError(f"Fallaron pasos críticos: {', '.join(fallidos)}")
        self.stdout.write(self.style.SUCCESS("Datos del frontend actualizados."))

    def correr_pasos(self, options) -> list[dict]:
        pasos = []

        def paso(nombre, funcion):
            self.stdout.write(f"== {nombre}")
            inicio = time.monotonic()
            ok, detalle = True, ""
            try:
                detalle = funcion() or ""
            except Omitido as motivo:
                detalle = f"omitido: {motivo}"
            except Exception as error:
                # se registra y se sigue: una caída de Copernicus no deja al frontend sin datos
                logger.exception("Falló el paso %s", nombre)
                ok, detalle = False, str(error) or type(error).__name__
            if detalle:
                self.stdout.write(f"   {detalle}")
            pasos.append(
                {
                    "paso": nombre,
                    "ok": ok,
                    "segundos": round(time.monotonic() - inicio, 2),
                    "detalle": detalle,
                }
            )
            return ok

        csv = settings.BASE_DIR / "data" / "ficticio" / "cosechas.csv"

        paso("generar_resumenes", lambda: call_command("generar_resumenes"))
        paso("calcular_indices", lambda: call_command("calcular_indices"))
        paso("clasificar_temporadas", lambda: self.clasificar(csv))
        paso("actualizar_mapa_calor", lambda: self.mapa_calor(options))

        evaluacion = csv.with_name("prediccion_cosecha_california.json")
        paso("entrenar_cosecha", lambda: self.entrenar(csv, evaluacion))
        paso("exportar_prediccion_ficticia", lambda: self.exportar_prediccion(evaluacion))

        paso(
            "exportar_json",
            lambda: call_command(
                "exportar_json",
                "--salida",
                str(settings.DATOS_DIR / "vigno-datos-reales.json"),
                "--sobrescribir",
            ),
        )
        return pasos

    def mapa_calor(self, options) -> str:
        if options["sin_satelite"]:
            raise Omitido("--sin-satelite")
        if not (settings.CDSE_CLIENT_ID and settings.CDSE_CLIENT_SECRET):
            raise Omitido("faltan CDSE_CLIENT_ID y CDSE_CLIENT_SECRET en .env")

        limite = timezone.localdate() - timedelta(days=DIAS_CAPA_VIGENTE)
        ultimas = dict(
            CapaSatelital.objects.filter(capa="ndvi")
            .values("estacion__codigo")
            .annotate(ultima=Max("fecha_imagen"))
            .values_list("estacion__codigo", "ultima")
        )
        actualizadas, vigentes, errores = [], [], []
        for codigo in estaciones_con_contorno():
            ultima = ultimas.get(codigo)
            if not options["forzar_satelite"] and ultima is not None and ultima > limite:
                vigentes.append(codigo)
                continue
            # cada estación por separado: si una falla, las demás igual se actualizan
            try:
                call_command("actualizar_mapa_calor", estacion=codigo, capa="ndvi")
                actualizadas.append(codigo)
            except Exception as error:
                logger.exception("Falló el mapa de calor de %s", codigo)
                errores.append(f"{codigo}: {error}")

        detalle = "; ".join(
            texto
            for texto in (
                actualizadas and f"actualizadas: {', '.join(actualizadas)}",
                vigentes and f"vigentes: {', '.join(vigentes)}",
                errores and f"con error: {'; '.join(errores)}",
            )
            if texto
        )
        if errores:
            raise RuntimeError(detalle)
        return detalle or "sin estaciones con contorno"

    def clasificar(self, csv) -> str:
        # clasifica el histórico de California, no las estaciones: sin el CSV no aplica
        if not csv.is_file():
            raise Omitido(f"no existe {csv.relative_to(settings.BASE_DIR)}")
        call_command("clasificar_temporadas")
        return ""

    def entrenar(self, csv, evaluacion) -> str:
        if not csv.is_file():
            raise Omitido(f"no existe {csv.relative_to(settings.BASE_DIR)}")
        if not hay_sklearn():
            raise Omitido("scikit-learn no está instalado (requirements-ml.txt)")
        if evaluacion.is_file() and evaluacion.stat().st_mtime >= csv.stat().st_mtime:
            return "la evaluación está al día con cosechas.csv"
        call_command("entrenar_cosecha")
        return ""

    def exportar_prediccion(self, evaluacion) -> str:
        # solo lee la evaluación: no necesita el CSV ni scikit-learn
        if not evaluacion.is_file():
            raise Omitido(f"no existe {evaluacion.relative_to(settings.BASE_DIR)}")
        call_command("exportar_prediccion_ficticia")
        return ""
