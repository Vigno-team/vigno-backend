"""Validación de consultas y contrato OpenAPI de los resultados."""

from rest_framework import serializers

from apps.clima import estaciones
from apps.clima.mapeos import es_nombre_reservado


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


class CalidadLluviaFueraInviernoSerializer(CalidadDatoSerializer):
    ventanas = serializers.DictField(child=CalidadDatoSerializer())
    en_curso = serializers.BooleanField()
    evaluado_hasta = serializers.DateField(allow_null=True)


class EtapaLluviaSerializer(serializers.Serializer):
    etapa = serializers.CharField()
    desde = serializers.DateField()
    hasta = serializers.DateField()
    mm = serializers.FloatField(allow_null=True)
    promedio_mm = serializers.FloatField(allow_null=True)
    diferencia_pct = serializers.FloatField(allow_null=True)
    temporadas_en_promedio = serializers.IntegerField(min_value=0)
    en_curso = serializers.BooleanField()
    evaluado_hasta = serializers.DateField(allow_null=True)


class DiaLluviaIntensaSerializer(serializers.Serializer):
    fecha = serializers.DateField()
    mm = serializers.FloatField()
    etapa = serializers.CharField()


class MesInusualSerializer(serializers.Serializer):
    mes = serializers.CharField()
    mm = serializers.FloatField()
    promedio_mm = serializers.FloatField()
    temporadas_en_promedio = serializers.IntegerField(min_value=0)


class LluviaFueraInviernoSerializer(serializers.Serializer):
    total_anio_agricola_mm = serializers.FloatField(allow_null=True)
    septiembre_mm = serializers.FloatField(allow_null=True)
    crecimiento_mm = serializers.FloatField(allow_null=True)
    etapas = EtapaLluviaSerializer(many=True)
    dias_lluvia_intensa = DiaLluviaIntensaSerializer(many=True)
    meses_inusuales = MesInusualSerializer(many=True)
    calidad_dato = CalidadLluviaFueraInviernoSerializer()
    motivo_nulo = serializers.CharField(required=False)


class CalorSerializer(serializers.Serializer):
    dias_sobre_umbral = serializers.IntegerField(allow_null=True)
    umbral_c = serializers.FloatField()
    rachas_con_incidencia = serializers.IntegerField(allow_null=True)
    racha_maxima_dias = serializers.IntegerField(allow_null=True)
    calidad_dato = CalidadDatoSerializer()
    motivo_nulo = serializers.CharField(required=False)


class ClasificacionTemporadaSerializer(serializers.Serializer):
    termica = serializers.ChoiceField(choices=("calida", "normal", "fria"), allow_null=True)
    hidrica = serializers.ChoiceField(choices=("lluviosa", "normal", "seca"), allow_null=True)
    criterio = serializers.CharField()
    en_curso = serializers.BooleanField()
    parcial_hasta = serializers.DateField(allow_null=True)
    motivo_nulo = serializers.CharField(required=False)


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
    lluvia_fuera_invierno = LluviaFueraInviernoSerializer()
    calor = CalorSerializer()
    clasificacion = ClasificacionTemporadaSerializer(allow_null=True)
    dias_criticos = DiaCriticoSerializer(many=True)
    dias_corregidos_a_mano = serializers.IntegerField(min_value=0)


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
    latitud = serializers.FloatField(allow_null=True)
    longitud = serializers.FloatField(allow_null=True)
    variables = serializers.ListField(child=serializers.CharField())
    fecha_inicio = serializers.DateField(allow_null=True)
    fecha_fin = serializers.DateField(allow_null=True)
    temporadas_disponibles = serializers.IntegerField()
    calidad_dato = CalidadDatoSerializer()


class EstacionNuevaSerializer(serializers.Serializer):
    nombre = serializers.CharField(max_length=100)
    latitud = serializers.FloatField()
    longitud = serializers.FloatField()
    subzona = serializers.CharField(
        max_length=50, required=False, allow_null=True, allow_blank=True
    )
    propietario = serializers.CharField(
        max_length=100, required=False, allow_null=True, allow_blank=True
    )

    def validate_nombre(self, value):
        if not estaciones.base_de_codigo(value):
            raise serializers.ValidationError("Debe tener al menos una letra o un número.")
        if es_nombre_reservado(value):
            raise serializers.ValidationError("Ese nombre está reservado.")
        return value

    @staticmethod
    def _finito(valor, campo):
        # float('nan') e inf pasan por FloatField y las comparaciones con ellos no fallan
        if valor != valor or valor in (float("inf"), float("-inf")):
            raise serializers.ValidationError({campo: "Debe ser un número finito."})

    def validate(self, datos):
        lat, lon = datos["latitud"], datos["longitud"]
        self._finito(lat, "latitud")
        self._finito(lon, "longitud")
        if not estaciones.en_chile(lat, lon):
            mensaje = "Las coordenadas están fuera de Chile."
            if estaciones.en_chile(lon, lat):
                mensaje += " ¿Intercambiaste latitud y longitud?"
            raise serializers.ValidationError({"coordenadas": mensaje})
        return datos


class EstacionCreadaSerializer(serializers.Serializer):
    """Mismos nombres que cada elemento de GET /estaciones (`id` es el código público)."""

    id = serializers.CharField(source="codigo", allow_null=True)
    nombre = serializers.CharField()
    subzona = serializers.CharField(allow_null=True)
    propietario = serializers.CharField(allow_null=True)
    latitud = serializers.FloatField(allow_null=True)
    longitud = serializers.FloatField(allow_null=True)


class EstacionRepetidaSerializer(serializers.Serializer):
    detail = serializers.CharField()
    estacion = EstacionCreadaSerializer()


class ErrorDetalleSerializer(serializers.Serializer):
    detail = serializers.CharField()


class ErrorConsultaSerializer(serializers.Serializer):
    estacion = serializers.ListField(child=serializers.CharField(), required=False)
    temporada = serializers.ListField(child=serializers.CharField(), required=False)
