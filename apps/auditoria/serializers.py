from rest_framework import serializers

from apps.auditoria.models import RegistroAuditoria


class RegistroAuditoriaSerializer(serializers.ModelSerializer):
    usuario = serializers.SerializerMethodField()
    usuario_id = serializers.IntegerField(read_only=True, allow_null=True)
    accion_texto = serializers.CharField(source="get_accion_display", read_only=True)

    def get_usuario(self, obj) -> str | None:
        return obj.usuario.email if obj.usuario_id else None

    class Meta:
        model = RegistroAuditoria
        fields = [
            "id",
            "fecha",
            "usuario",
            "usuario_id",
            "accion",
            "accion_texto",
            "tipo_objeto",
            "id_objeto",
            "valor_anterior",
            "valor_nuevo",
            "ip",
        ]
        read_only_fields = fields


class FiltrosAuditoriaSerializer(serializers.Serializer):
    usuario = serializers.CharField(required=False, help_text="Id o correo de la cuenta")
    accion = serializers.ChoiceField(choices=RegistroAuditoria.Accion.choices, required=False)
    desde = serializers.DateField(required=False)
    hasta = serializers.DateField(required=False)

    def validate(self, datos):
        if "desde" in datos and "hasta" in datos and datos["desde"] > datos["hasta"]:
            raise serializers.ValidationError({"hasta": "Debe ser igual o posterior a desde."})
        return datos
