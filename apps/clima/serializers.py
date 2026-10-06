"""Validación de consultas y contrato OpenAPI de los resultados."""

from rest_framework import serializers


class ConsultaTemporadaSerializer(serializers.Serializer):
    estacion = serializers.CharField(max_length=50)
    temporada = serializers.RegexField(r"\A[0-9]{4}-[0-9]{4}\Z")

    def validate_temporada(self, value):
        inicio, fin = (int(anio) for anio in value.split("-"))
        if inicio < 1 or fin != inicio + 1:
            raise serializers.ValidationError("Usa dos años consecutivos, por ejemplo 2024-2025.")
        return value


class CalidadDatoSerializer(serializers.Serializer):
    completitud_pct = serializers.FloatField(allow_null=True, min_value=0, max_value=100)
    confiable = serializers.BooleanField()
    umbral_completitud_pct = serializers.FloatField()
    resolucion_origen = serializers.ChoiceField(
        choices=("diaria", "horaria", "mixta"), allow_null=True
    )
    version_calculo = serializers.CharField(allow_null=True)


class WinklerSerializer(serializers.Serializer):
    valor = serializers.FloatField(allow_null=True)
    region = serializers.ChoiceField(choices=("I", "II", "III", "IV", "V"), allow_null=True)
    calidad_dato = CalidadDatoSerializer()
    motivo_nulo = serializers.CharField(required=False)


class HuglinSerializer(serializers.Serializer):
    valor = serializers.FloatField(allow_null=True)
    clasificacion = serializers.CharField(allow_null=True)
    calidad_dato = CalidadDatoSerializer()
    motivo_nulo = serializers.CharField(required=False)


class IndicesSerializer(serializers.Serializer):
    winkler = WinklerSerializer()
    huglin = HuglinSerializer()


class PeriodoSerializer(serializers.Serializer):
    inicio = serializers.DateField()
    fin = serializers.DateField()


class LluviaInvernalSerializer(serializers.Serializer):
    acumulado_mm = serializers.FloatField(allow_null=True)
    promedio_historico_mm = serializers.FloatField(allow_null=True)
    diferencia_pct = serializers.FloatField(allow_null=True)
    calidad_dato = CalidadDatoSerializer()
    motivo_nulo = serializers.CharField(required=False)


class CalorSerializer(serializers.Serializer):
    dias_sobre_umbral = serializers.IntegerField(allow_null=True)
    umbral_c = serializers.FloatField()
    rachas_con_incidencia = serializers.IntegerField(allow_null=True)
    racha_maxima_dias = serializers.IntegerField(allow_null=True)
    calidad_dato = CalidadDatoSerializer()
    motivo_nulo = serializers.CharField(required=False)


class ClasificacionTemporadaSerializer(serializers.Serializer):
    termica = serializers.ChoiceField(choices=("calida", "normal", "fria"))
    hidrica = serializers.ChoiceField(choices=("lluviosa", "normal", "seca"))
    criterio = serializers.CharField()


class DiaCriticoSerializer(serializers.Serializer):
    fecha = serializers.DateField()
    tmax = serializers.FloatField()


class FichaTemporadaSerializer(serializers.Serializer):
    temporada = serializers.CharField()
    estacion_id = serializers.CharField()
    subzona = serializers.CharField(allow_null=True)
    periodo = PeriodoSerializer()
    indices = IndicesSerializer()
    lluvia_invernal = LluviaInvernalSerializer()
    calor = CalorSerializer()
    clasificacion = ClasificacionTemporadaSerializer(allow_null=True)
    dias_criticos = DiaCriticoSerializer(many=True)


class RachaSerializer(serializers.Serializer):
    inicio = serializers.DateField()
    fin = serializers.DateField()
    dias = serializers.IntegerField()
    tmax_maxima = serializers.FloatField()
    con_incidencia = serializers.BooleanField()
    interrumpida_por_dato_faltante = serializers.BooleanField()


class RachasTemporadaSerializer(serializers.Serializer):
    temporada = serializers.CharField()
    estacion_id = serializers.CharField()
    umbral_c = serializers.FloatField()
    minimo_dias_incidencia = serializers.IntegerField()
    rachas = RachaSerializer(many=True)
    calidad_dato = CalidadDatoSerializer()


class EstacionResultadoSerializer(serializers.Serializer):
    id = serializers.CharField(allow_null=True)
    nombre = serializers.CharField()
    subzona = serializers.CharField(allow_null=True)
    propietario = serializers.CharField(allow_null=True)
    variables = serializers.ListField(child=serializers.CharField())
    fecha_inicio = serializers.DateField(allow_null=True)
    fecha_fin = serializers.DateField(allow_null=True)
    temporadas_disponibles = serializers.IntegerField()
    calidad_dato = CalidadDatoSerializer()


class ErrorDetalleSerializer(serializers.Serializer):
    detail = serializers.CharField()


class ErrorConsultaSerializer(serializers.Serializer):
    estacion = serializers.ListField(child=serializers.CharField(), required=False)
    temporada = serializers.ListField(child=serializers.CharField(), required=False)
