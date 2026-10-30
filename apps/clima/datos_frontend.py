"""E1C-93: archivos agregados del dashboard, publicados por E1C-129 y E1C-124."""

import json
import logging
from hashlib import sha256

from django.conf import settings
from django.db import DatabaseError
from django.utils.http import parse_etags, quote_etag
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.response import Response

from apps.clima.archivos import escribir_json_atomico
from apps.clima.management.commands.actualizar_todo import candado
from apps.clima.management.commands.exportar_json import NOMBRE_SALIDA, exportar
from apps.clima.views import ResultadosView

logger = logging.getLogger(__name__)


def _no_finito(valor):
    raise ValueError(f"Número no finito: {valor}")


def _leer(ruta):
    datos = json.loads(ruta.read_text(encoding="utf-8"), parse_constant=_no_finito)
    if not isinstance(datos, dict):
        raise ValueError("Se esperaba un objeto JSON")
    return datos


def _datos_publicados():
    ruta = settings.DATOS_DIR / NOMBRE_SALIDA
    try:
        return _leer(ruta)
    except FileNotFoundError:
        # Compartido con actualizar_todo: no publicar una exportación vieja sobre la nueva.
        with candado():
            try:
                return _leer(ruta)
            except FileNotFoundError:
                datos = exportar()
                escribir_json_atomico(ruta, datos)
                return datos


def _no_disponible(detalle):
    return Response(
        {"detalle": detalle},
        status=503,
        headers={"Retry-After": "30", "Cache-Control": "no-store"},
    )


def _respuesta_condicional(request, datos):
    # Incluye generado y el contenido: dos exportaciones en el mismo segundo pueden diferir.
    contenido = json.dumps(datos, sort_keys=True, ensure_ascii=True, allow_nan=False)
    etag = "W/" + quote_etag(sha256(contenido.encode("utf-8")).hexdigest())
    headers = {"ETag": etag, "Cache-Control": "no-cache"}
    candidatos = parse_etags(request.headers.get("If-None-Match", ""))
    if "*" in candidatos or any(
        candidato.removeprefix("W/") == etag.removeprefix("W/") for candidato in candidatos
    ):
        return Response(status=304, headers=headers)
    return Response(datos, headers=headers)


PARAMETROS_CACHE = [
    OpenApiParameter(
        "If-None-Match",
        str,
        OpenApiParameter.HEADER,
        description="ETag recibido anteriormente; si coincide devuelve 304 sin cuerpo.",
    ),
    OpenApiParameter(
        "ETag",
        str,
        OpenApiParameter.HEADER,
        response=[200, 304],
        description="Validador que incluye generado y el contenido del JSON.",
    ),
    OpenApiParameter(
        "Cache-Control",
        str,
        OpenApiParameter.HEADER,
        response=[200, 304],
        description="no-cache: validar con el servidor antes de reutilizar.",
    ),
]


class DatosFrontendView(ResultadosView):
    @extend_schema(
        summary="Datos consolidados para el frontend",
        operation_id="dashboard_datos",
        tags=["Dashboard"],
        description=(
            "Contrato completo de vigno-datos-reales.json, publicado en DATOS_DIR por "
            "actualizar_todo. Si aún no existe, exporta los resultados de la base y lo guarda "
            "atómicamente. No ejecuta ingesta ni entrenamiento. Usa ETag y Cache-Control: no-cache."
        ),
        parameters=PARAMETROS_CACHE,
        responses={
            200: dict,
            304: OpenApiResponse(description="Sin cambios; sin cuerpo"),
            503: dict,
        },
    )
    def get(self, request):
        try:
            return _respuesta_condicional(request, _datos_publicados())
        except (OSError, ValueError, DatabaseError):
            logger.exception("No se pudieron servir los datos del dashboard")
            return _no_disponible("No se pudieron publicar los datos. Ejecuta actualizar_todo.")


class PrediccionFicticiaView(ResultadosView):
    @extend_schema(
        summary="Predicción ficticia del modelo de California",
        operation_id="dashboard_prediccion_ficticia",
        tags=["Dashboard"],
        description=(
            "Devuelve data/ficticio/prediccion_ficticia.json (E1C-124) sin entrenar ni "
            "modificar su contenido. Si falta, devuelve 404 con motivo_nulo."
        ),
        responses={200: dict, 404: dict, 503: dict},
    )
    def get(self, request):
        try:
            datos = _leer(settings.BASE_DIR / "data" / "ficticio" / "prediccion_ficticia.json")
        except FileNotFoundError:
            return Response(
                {"motivo_nulo": "Aún no se ha entrenado el modelo de California."},
                status=404,
                headers={"Cache-Control": "no-store"},
            )
        except (OSError, ValueError):
            logger.exception("No se pudo leer la predicción ficticia")
            return _no_disponible("No se pudo leer la predicción ficticia.")
        return Response(datos, headers={"Cache-Control": "no-cache"})


class ActualizacionView(ResultadosView):
    @extend_schema(
        summary="Estado de la última actualización",
        operation_id="dashboard_actualizacion",
        tags=["Dashboard"],
        description=(
            "Devuelve actualizacion.json de E1C-129: generado, ok y pasos (paso, ok, "
            'segundos, detalle). Si nunca ha corrido, devuelve {"generado": null}. '
            "Consultar cada 60 segundos; volver a pedir /datos si generado cambia."
        ),
        responses={200: dict, 503: dict},
    )
    def get(self, request):
        try:
            datos = _leer(settings.DATOS_DIR / "actualizacion.json")
        except FileNotFoundError:
            datos = {"generado": None}
        except (OSError, ValueError):
            logger.exception("No se pudo leer el estado de actualización")
            return _no_disponible("No se pudo leer el estado de actualización.")
        return Response(datos, headers={"Cache-Control": "no-cache"})
