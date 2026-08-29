"""Endpoints transversales del sistema."""

from django.db import connection
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthCheckView(APIView):
    """Verifica que la API responde y que la base de datos esta accesible."""

    authentication_classes = []
    permission_classes = []

    @extend_schema(
        summary="Estado del servicio",
        description=(
            "Devuelve el estado de la API y de la conexion a PostgreSQL. "
            "Lo usa el equipo para confirmar que el entorno levanto bien."
        ),
        responses={200: None, 503: None},
    )
    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                cursor.fetchone()
            db_ok = True
        except Exception:
            db_ok = False

        payload = {
            "status": "ok" if db_ok else "degraded",
            "servicio": "vigno-backend",
            "version": "0.1.0",
            "base_datos": "conectada" if db_ok else "sin conexion",
        }
        codigo = status.HTTP_200_OK if db_ok else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response(payload, status=codigo)
