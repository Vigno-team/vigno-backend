"""Instala un catálogo validado y activa su configuración sin borrar mediciones."""

import json
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.clima.archivos import escribir_json_atomico
from apps.clima.areas_mapa import AreasMapaError, cargar_areas
from apps.clima.estaciones import en_territorio
from apps.clima.mapeos import es_nombre_reservado, normalizar_nombre
from apps.clima.models import Estacion
from vigno.instancia import cargar_configuracion


class Command(BaseCommand):
    help = "Carga una carpeta de instancia de forma idempotente y activa config/instancia.json."

    def add_arguments(self, parser):
        parser.add_argument("carpeta")
        parser.add_argument(
            "--sin-activar",
            action="store_true",
            help="Carga el catálogo sin escribir configuración (instancia ya seleccionada por el operador).",
        )

    def handle(self, *args, **options):
        carpeta = Path(options["carpeta"]).resolve()
        try:
            perfil = cargar_configuracion(carpeta / "instancia.json")
            filas = json.loads((carpeta / "estaciones.json").read_text(encoding="utf-8"))
            if not isinstance(filas, list):
                raise ValueError("estaciones.json debe ser una lista")
            mapeos = json.loads(
                (settings.BASE_DIR / perfil["archivos"]["mapeos"]).read_text(encoding="utf-8")
            )
            if not isinstance(mapeos, dict) or "formato_estandar" not in mapeos:
                raise ValueError("El mapeo debe contener formato_estandar")
            from zoneinfo import ZoneInfo

            for nombre, mapeo in mapeos.items():
                if not isinstance(mapeo, dict) or not mapeo.get("formatos"):
                    raise ValueError(f"Mapeo inválido: {nombre}")
                ZoneInfo(mapeo.get("zona_horaria", perfil["zona_horaria"]))
            areas = cargar_areas(
                settings.BASE_DIR / perfil["archivos"]["areas"],
                limites=perfil["limites_geograficos"],
                permitir_vacio=True,
            )
            codigos, nombres = set(), set()
            for fila in filas:
                if not isinstance(fila, dict) or set(fila) != {
                    "nombre",
                    "codigo",
                    "subzona",
                    "propietario",
                    "latitud",
                    "longitud",
                }:
                    raise ValueError(
                        "Cada estación requiere nombre, codigo, subzona, propietario, latitud y longitud"
                    )
                nombre = normalizar_nombre(fila["nombre"])
                if not fila["codigo"] or not nombre or es_nombre_reservado(fila["nombre"]):
                    raise ValueError("Nombre o código de estación inválido")
                if fila["codigo"] in codigos or nombre in nombres:
                    raise ValueError("Hay códigos o nombres de estación repetidos")
                codigos.add(fila["codigo"])
                nombres.add(nombre)
                Estacion(**fila).clean_fields()
                lat, lon = fila["latitud"], fila["longitud"]
                if lat is not None and (type(lat) not in (int, float) or not -90 <= lat <= 90):
                    raise ValueError("Latitud inválida")
                if lon is not None and (type(lon) not in (int, float) or not -180 <= lon <= 180):
                    raise ValueError("Longitud inválida")
                if (
                    lat is not None
                    and lon is not None
                    and not en_territorio(lat, lon, perfil["limites_geograficos"])
                ):
                    raise ValueError("La estación queda fuera del territorio configurado")
            if any(area.codigo not in codigos for area in areas):
                raise ValueError("Hay áreas con códigos que no están en estaciones.json")
        except (
            OSError,
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            ImproperlyConfigured,
            ValidationError,
            AreasMapaError,
        ) as error:
            raise CommandError(f"Instancia inválida: {error}") from error

        destino = settings.INSTANCIA_CONFIG
        anterior = destino.read_bytes() if destino.exists() else None
        escrito = False
        try:
            with transaction.atomic():
                existentes = list(Estacion.objects.select_for_update())
                for fila in filas:
                    for est in existentes:
                        if (
                            normalizar_nombre(est.nombre) == normalizar_nombre(fila["nombre"])
                            and est.codigo != fila["codigo"]
                        ):
                            raise CommandError(
                                f"{fila['nombre']} ya existe con otro código ({est.codigo})"
                            )
                    Estacion.objects.update_or_create(
                        codigo=fila["codigo"],
                        defaults={k: v for k, v in fila.items() if k != "codigo"},
                    )
                for area in areas:
                    Estacion.objects.filter(codigo=area.codigo).update(
                        latitud=area.latitud, longitud=area.longitud
                    )
                if not options["sin_activar"]:
                    escribir_json_atomico(destino, perfil)
                    escrito = True
        except Exception as error:
            if escrito:
                if anterior is None:
                    destino.unlink(missing_ok=True)
                else:
                    escribir_json_atomico(destino, json.loads(anterior))
            if isinstance(error, CommandError):
                raise
            raise CommandError(f"No se pudo cargar la instancia: {error}") from error
        self.stdout.write(
            self.style.SUCCESS(
                f"{perfil['organizacion']['nombre']}: {len(filas)} estaciones cargadas."
            )
        )
        if not options["sin_activar"]:
            self.stdout.write(
                f"Configuración guardada en {destino}. Reinicia backend y tareas para aplicarla."
            )
