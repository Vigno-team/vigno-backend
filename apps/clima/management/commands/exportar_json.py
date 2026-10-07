import json
from pathlib import Path

import pandas as pd
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Max, Min
from rest_framework.exceptions import NotFound

from apps.clima import resultados, serializers, services
from apps.clima.models import Estacion, ResumenDiario
from apps.clima.services import HAY_DATO, TZ
from apps.clima.temporadas import temporada_de

SALIDA = "data/cliente/vigno-datos-reales.json"


def exportar() -> dict:
    ahora = pd.Timestamp.now(tz=TZ)
    resumen, fichas, rachas = [], [], []

    for est in Estacion.objects.order_by("nombre"):
        dias = ResumenDiario.objects.filter(HAY_DATO, estacion=est)
        rango = dias.aggregate(desde=Min("fecha"), hasta=Max("fecha"))
        if rango["desde"] is None:
            continue
        resumen.append(
            services.resumen_diario(
                est.codigo, rango["desde"].isoformat(), rango["hasta"].isoformat()
            )
        )

        # sin el order_by, distinct no saca las temporadas repetidas
        temporadas = dias.order_by("temporada").values_list("temporada", flat=True).distinct()
        for temporada in temporadas:
            try:
                ficha = resultados.ficha_temporada(est, temporada)
            except NotFound:
                continue
            fichas.append(serializers.FichaTemporadaSerializer(ficha).data)
            rachas.append(
                serializers.RachasTemporadaSerializer(
                    resultados.resultados_rachas(est, temporada)
                ).data
            )

    return {
        "generado": ahora.isoformat(timespec="seconds"),
        "temporada_en_curso": temporada_de(ahora.date()),
        "estaciones": serializers.EstacionResultadoSerializer(
            services.estaciones(), many=True
        ).data,
        "temporadas": services.temporadas(),
        "completitud_por_temporada": services.completitud_por_temporada(),
        "resumen_diario": resumen,
        "ficha_temporada": fichas,
        "rachas": rachas,
    }


class Command(BaseCommand):
    help = "E1C-48: exporta los resultados a un JSON con el formato del contrato para el frontend."

    def add_arguments(self, parser):
        parser.add_argument("--salida", default=SALIDA)
        parser.add_argument("--sobrescribir", action="store_true")

    def handle(self, *args, **options):
        salida = Path(options["salida"])
        if salida.exists() and not options["sobrescribir"]:
            raise CommandError(f"{salida} ya existe, usa --sobrescribir para reemplazarlo.")

        datos = exportar()
        salida.parent.mkdir(parents=True, exist_ok=True)
        salida.write_text(
            json.dumps(datos, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
        )
        self.stdout.write(
            f"{salida}: {len(datos['estaciones'])} estaciones, "
            f"{len(datos['ficha_temporada'])} fichas de temporada"
        )
