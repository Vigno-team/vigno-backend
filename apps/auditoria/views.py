"""GET /api/v1/auditoria: la bitácora, solo para administradores."""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.generics import ListAPIView

from apps.auditoria.models import RegistroAuditoria
from apps.auditoria.serializers import FiltrosAuditoriaSerializer, RegistroAuditoriaSerializer
from apps.cuentas.permisos import EsAdministrador


class AuditoriaView(ListAPIView):
    permission_classes = [EsAdministrador]
    serializer_class = RegistroAuditoriaSerializer

    def get_queryset(self):
        registros = RegistroAuditoria.objects.select_related("usuario")
        if getattr(self, "swagger_fake_view", False):  # al generar /api/schema/
            return registros.none()
        filtros = FiltrosAuditoriaSerializer(data=self.request.query_params)
        filtros.is_valid(raise_exception=True)
        datos = filtros.validated_data

        usuario = datos.get("usuario", "").strip()
        if usuario.isdigit():
            registros = registros.filter(usuario_id=int(usuario))
        elif usuario:
            registros = registros.filter(usuario__email__iexact=usuario)
        if "accion" in datos:
            registros = registros.filter(accion=datos["accion"])
        # Fecha local (TIME_ZONE de la instancia); ambos extremos se incluyen.
        if "desde" in datos:
            registros = registros.filter(fecha__date__gte=datos["desde"])
        if "hasta" in datos:
            registros = registros.filter(fecha__date__lte=datos["hasta"])
        return registros

    @extend_schema(
        summary="Bitácora de auditoría: quién hizo cada cambio",
        description=(
            "Solo administrador. Paginada, de la más reciente a la más antigua, con el valor "
            "anterior y el nuevo de cada cambio."
        ),
        parameters=[
            OpenApiParameter("usuario", str, description="Id o correo de la cuenta"),
            OpenApiParameter(
                "accion", str, enum=[valor for valor, _ in RegistroAuditoria.Accion.choices]
            ),
            OpenApiParameter("desde", OpenApiTypes.DATE, description="AAAA-MM-DD, inclusive"),
            OpenApiParameter("hasta", OpenApiTypes.DATE, description="AAAA-MM-DD, inclusive"),
        ],
        tags=["Auditoría"],
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)
