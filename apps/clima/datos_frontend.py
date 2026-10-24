"""Lectura del archivo publicado atómicamente por actualizar_todo."""

import json

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response

from apps.clima.views import ResultadosView


class DatosFrontendView(ResultadosView):
    @extend_schema(summary="Datos consolidados para el frontend", responses={200: dict, 503: dict})
    def get(self, request):
        try:
            with (settings.DATOS_DIR / "vigno-datos-reales.json").open(encoding="utf-8") as archivo:
                datos = json.load(archivo)
            if not isinstance(datos, dict):
                raise ValueError("Se esperaba un objeto JSON")
        except (OSError, ValueError):
            return Response(
                {"detalle": "Los datos aún no están disponibles. Ejecuta actualizar_todo."},
                status=503,
                headers={"Retry-After": "30", "Cache-Control": "no-store"},
            )
        return Response(datos, headers={"Cache-Control": "no-store"})
