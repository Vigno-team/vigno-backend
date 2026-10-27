"""Carga de Excel por API (E1C-66): POST /api/v1/cargas y su historial."""

import io
import json
import logging
import re

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.clima.management.commands.actualizar_todo import candado
from apps.clima.mapeos import EstacionNoExiste, estacion_y_mapeo
from apps.clima.models import Estacion
from apps.ingesta import carga
from apps.ingesta.autenticacion import ApiKeyPrivadaAuthentication
from apps.ingesta.models import RegistroCarga

logger = logging.getLogger(__name__)

ULTIMAS = 20


def _rechazo(codigo, errores):
    return Response({"valido": False, "errores": errores}, status=codigo)


def _resumen(c: RegistroCarga) -> dict:
    return {
        "id": c.pk,
        "fecha_carga": c.fecha_carga.isoformat(),
        "archivo": c.archivo,
        "estacion": c.estacion,
        "temporada": c.temporada,
        "formato": c.formato_detectado,
        "estado": c.estado,
        "fecha_desde": c.fecha_desde.isoformat() if c.fecha_desde else None,
        "fecha_hasta": c.fecha_hasta.isoformat() if c.fecha_hasta else None,
        "filas": {
            "leidas": c.filas_leidas,
            "aceptadas": c.filas_aceptadas,
            "rechazadas": c.filas_rechazadas,
            "vacias_ignoradas": c.filas_vacias_ignoradas,
        },
        "conteos": {
            "insertados": c.registros_insertados,
            "actualizados": c.registros_actualizados,
            "sin_cambio": c.registros_sin_cambio,
            "omitidos": c.registros_omitidos,
            "rechazados": c.filas_rechazadas,
        },
    }


def _conservadas(celdas) -> list[dict]:
    return [{**celda, "aviso": carga.AVISO_VACIO_CONSERVADO} for celda in celdas]


def _detalle(c: RegistroCarga) -> dict:
    return {
        **_resumen(c),
        "rechazos": c.detalle_rechazos or [],
        "celdas_vacias_conservadas": _conservadas(c.celdas_vacias_conservadas or []),
        "error": c.error,
    }


def _estacion(valor: str):
    """Acepta el código (el `id` del resto de la API) o el nombre de la estación."""
    por_codigo = Estacion.objects.filter(codigo=valor).first()
    return estacion_y_mapeo(por_codigo.nombre if por_codigo else valor)


def _recalcular() -> dict:
    """actualizar_todo deja su resultado en actualizacion.json (E1C-129)."""
    try:
        call_command("actualizar_todo", "--sin-satelite", stdout=io.StringIO())
    except CommandError:
        logger.exception("El recálculo después de la carga terminó con error")
    try:
        estado = json.loads((settings.DATOS_DIR / "actualizacion.json").read_text(encoding="utf-8"))
        return {"ok": estado["ok"], "generado": estado["generado"], "pasos": estado["pasos"]}
    except (OSError, ValueError, KeyError):
        return {"ok": False, "generado": None, "pasos": []}


class CargasView(APIView):
    authentication_classes = [ApiKeyPrivadaAuthentication]
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(
        summary="Últimas cargas de Excel",
        operation_id="cargas_listar",
        responses={200: dict, 401: dict},
        tags=["Cargas"],
    )
    def get(self, request):
        cargas = RegistroCarga.objects.order_by("-fecha_carga", "-pk")[:ULTIMAS]
        return Response([_resumen(c) for c in cargas])

    @extend_schema(
        summary="Sube un Excel de una estación, lo valida, lo guarda y recalcula todo",
        operation_id="cargas_crear",
        description=(
            "Multipart con `archivo` (.xls o .xlsx), `estacion` (código o nombre de una "
            "estación registrada) y `temporada` opcional (año). Con `?solo_validar=1` devuelve "
            "lo que pasaría sin guardar nada. El mismo archivo ya cargado responde 200 sin "
            "procesarlo de nuevo. Requiere la cabecera X-Api-Key."
        ),
        parameters=[OpenApiParameter("solo_validar", bool)],
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "archivo": {"type": "string", "format": "binary"},
                    "estacion": {"type": "string"},
                    "temporada": {"type": "integer"},
                },
                "required": ["archivo", "estacion"],
            }
        },
        responses={200: dict, 201: dict, 400: dict, 401: dict, 422: dict},
        tags=["Cargas"],
    )
    def post(self, request):
        umbrales = carga.cargar_umbrales()
        solo_validar = request.query_params.get("solo_validar", "").lower() in ("1", "true", "si")

        archivo = request.FILES.get("archivo")
        nombre_estacion = (request.data.get("estacion") or "").strip()
        texto_temporada = (request.data.get("temporada") or "").strip()
        errores = []
        if archivo is None:
            errores.append("Falta el archivo.")
        if not nombre_estacion:
            errores.append("Falta la estación.")
        if texto_temporada and not re.fullmatch(r"(19|20)\d{2}", texto_temporada):
            errores.append("La temporada debe ser un año, por ejemplo 2024.")
        if archivo is not None:
            nombre = archivo.name or ""
            extension = ("." + nombre.rsplit(".", 1)[-1].lower()) if "." in nombre else ""
            if extension not in umbrales["extensiones"]:
                errores.append(
                    f"El archivo debe ser {' o '.join(umbrales['extensiones'])} "
                    f"(llegó '{nombre}')."
                )
            maximo = umbrales["tamano_maximo_mb"] * 1024 * 1024
            if archivo.size > maximo:
                errores.append(
                    f"El archivo pesa {archivo.size / 1024 / 1024:.1f} MB; "
                    f"el máximo es {umbrales['tamano_maximo_mb']} MB."
                )
        if errores:
            return _rechazo(status.HTTP_400_BAD_REQUEST, errores)
        try:
            estacion, config = _estacion(nombre_estacion)
        except EstacionNoExiste as error:
            return _rechazo(status.HTTP_400_BAD_REQUEST, [str(error)])

        contenido = archivo.read()
        hash_del_archivo = carga.hash_archivo(contenido)
        temporada = int(texto_temporada) if texto_temporada else None

        if solo_validar:
            return self._procesar(
                contenido,
                nombre,
                extension,
                hash_del_archivo,
                estacion,
                config,
                temporada,
                umbrales,
                solo_validar=True,
            )
        # La carga por API y las tareas programadas no se pisan (mismo candado que actualizar_todo).
        with candado():
            return self._procesar(
                contenido,
                nombre,
                extension,
                hash_del_archivo,
                estacion,
                config,
                temporada,
                umbrales,
                solo_validar=False,
            )

    def _procesar(
        self,
        contenido,
        nombre,
        extension,
        hash_del_archivo,
        estacion,
        config,
        temporada,
        umbrales,
        solo_validar,
    ):
        previa = (
            RegistroCarga.objects.filter(
                hash_archivo=hash_del_archivo,
                estacion=estacion.nombre,
                estado=RegistroCarga.ESTADO_OK,
            )
            .order_by("-pk")
            .first()
        )
        if previa is not None and not solo_validar:
            return Response(
                {"valido": True, "repetida": True, **_detalle(previa), "recalculo": None},
                status=status.HTTP_200_OK,
            )

        try:
            prep = carga.preparar(
                io.BytesIO(contenido), nombre, estacion, config, temporada, "indicada en la carga"
            )
        except carga.ErrorCarga as error:
            return _rechazo(status.HTTP_422_UNPROCESSABLE_ENTITY, error.errores)
        except Exception:
            # un archivo raro puede fallar más adentro del lector; no debe terminar en 500
            logger.exception("No se pudo leer el Excel %s", nombre)
            return _rechazo(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                ["No se pudo leer el archivo: revisa que sea un Excel de la estación sin daños."],
            )
        errores = carga.validar_umbrales(prep, umbrales)
        if errores:
            return _rechazo(status.HTTP_422_UNPROCESSABLE_ENTITY, errores)

        clasificacion = carga.clasificar(prep)
        advertencias = prep.advertencias()
        if clasificacion.conservados:
            advertencias.append(
                f"{carga.AVISO_VACIO_CONSERVADO} ({len(clasificacion.conservados)} celdas)."
            )

        if solo_validar:
            if previa is not None:
                advertencias.append(f"Este archivo ya se cargó (carga {previa.pk}).")
            desde, hasta = prep.rango_fechas()
            limpieza = prep.limpieza
            return Response(
                {
                    "valido": True,
                    "solo_validar": True,
                    "estacion": estacion.nombre,
                    "estacion_id": estacion.codigo,
                    "temporada": prep.temporada,
                    "origen_temporada": prep.origen_temporada,
                    "formato": prep.formato,
                    "fecha_desde": desde.isoformat() if desde else None,
                    "fecha_hasta": hasta.isoformat() if hasta else None,
                    "filas": {
                        "leidas": limpieza.filas_leidas,
                        "aceptadas": len(limpieza.df_limpio),
                        "rechazadas": len(limpieza.rechazos),
                        "vacias_ignoradas": limpieza.filas_vacias_ignoradas,
                    },
                    "conteos": {
                        "insertados": clasificacion.insertados,
                        "actualizados": clasificacion.actualizados,
                        "sin_cambio": clasificacion.sin_cambio,
                        "omitidos": clasificacion.omitidos,
                        "rechazados": len(limpieza.rechazos),
                    },
                    "rechazos": limpieza.rechazos,
                    "celdas_vacias_conservadas": _conservadas(clasificacion.conservados),
                    "advertencias": advertencias,
                }
            )

        carpeta = settings.DATOS_DIR / "cargas"
        carpeta.mkdir(parents=True, exist_ok=True)
        (carpeta / f"{hash_del_archivo}{extension}").write_bytes(contenido)

        registro = carga.guardar(
            prep, clasificacion, nombre[:255], hash_del_archivo, usuario="API (X-Api-Key)"
        )
        return Response(
            {
                "valido": True,
                "repetida": False,
                **_detalle(registro),
                "estacion_id": estacion.codigo,
                "origen_temporada": prep.origen_temporada,
                "advertencias": advertencias,
                "recalculo": _recalcular(),
            },
            status=status.HTTP_201_CREATED,
        )


class CargaView(APIView):
    authentication_classes = [ApiKeyPrivadaAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="Detalle de una carga: estado, filas y rechazos con su motivo",
        operation_id="cargas_obtener",
        responses={200: dict, 401: dict, 404: dict},
        tags=["Cargas"],
    )
    def get(self, request, pk):
        return Response(_detalle(get_object_or_404(RegistroCarga, pk=pk)))
