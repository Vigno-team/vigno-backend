# E1C-107: diferencias propuestas del JSON de referencia

Base: `origin/refactor` en `2399dbc`. Solo se permiten diferencias en la métrica
de días de calor: valor, motivo de ausencia y sus metadatos de calidad.
La comparación completa comprobó que el resto del JSON conserva sus valores.
Las rachas y días críticos mantienen su ventana anual.

La nueva regla es octubre–abril para conteo y completitud, desde
`temporadas.rango_dias_calor`, y `settings.UMBRAL_CALOR_C` para el umbral.
La calidad del bloque `calor` describe esa métrica; el recurso `rachas` conserva
su calidad anual. La versión pasa a `dias_umbral-v2_35c_1001-0430` con umbral 35.

**Revisar estas diferencias con el equipo antes de mergear**, según E1C-120.
La referencia actualizada se entrega como propuesta explícita en el PR.
Se generó en una copia temporal y luego se volvió a ejecutar el test sin
`REGENERAR_REFERENCIA`; no se omite la comprobación en la suite final.

En los datos sintéticos, la estación Sur 2021-2022 solo tiene temperaturas fuera
de la ventana de calor: pasa de cero a `null`, con motivo. En Sur 2023-2024,
la completitud pasa de 85% anual a 74,2% en octubre–abril y deja de ser confiable.

## Diferencias exactas

17 diferencias:

```text
$.ficha_temporada[0: estacion_id=sint-norte-01, temporada=2021-2022].calor.calidad_dato.version_calculo: antes 'rachas-v1_35c_min5_temporada', ahora 'dias_umbral-v2_35c_1001-0430'
$.ficha_temporada[1: estacion_id=sint-norte-01, temporada=2022-2023].calor.calidad_dato.completitud_pct: antes 97.3, ahora 98.6
$.ficha_temporada[1: estacion_id=sint-norte-01, temporada=2022-2023].calor.calidad_dato.version_calculo: antes 'rachas-v1_35c_min5_temporada', ahora 'dias_umbral-v2_35c_1001-0430'
$.ficha_temporada[2: estacion_id=sint-norte-01, temporada=2023-2024].calor.calidad_dato.completitud_pct: antes 99.2, ahora 98.6
$.ficha_temporada[2: estacion_id=sint-norte-01, temporada=2023-2024].calor.calidad_dato.version_calculo: antes 'rachas-v1_35c_min5_temporada', ahora 'dias_umbral-v2_35c_1001-0430'
$.ficha_temporada[3: estacion_id=sint-norte-01, temporada=2024-2025].calor.calidad_dato.completitud_pct: antes 99.2, ahora 99.5
$.ficha_temporada[3: estacion_id=sint-norte-01, temporada=2024-2025].calor.calidad_dato.version_calculo: antes 'rachas-v1_35c_min5_temporada', ahora 'dias_umbral-v2_35c_1001-0430'
$.ficha_temporada[4: estacion_id=sint-sur-01, temporada=2021-2022].calor.motivo_nulo: sobra (vale 'Sin temperaturas máximas en la ventana de días de calor.')
$.ficha_temporada[4: estacion_id=sint-sur-01, temporada=2021-2022].calor.calidad_dato.completitud_pct: antes 16.7, ahora 0.0
$.ficha_temporada[4: estacion_id=sint-sur-01, temporada=2021-2022].calor.calidad_dato.resolucion_origen: antes 'diaria', ahora None
$.ficha_temporada[4: estacion_id=sint-sur-01, temporada=2021-2022].calor.calidad_dato.version_calculo: antes 'rachas-v1_35c_min5_temporada', ahora 'dias_umbral-v2_35c_1001-0430'
$.ficha_temporada[4: estacion_id=sint-sur-01, temporada=2021-2022].calor.dias_sobre_umbral: antes 0, ahora None
$.ficha_temporada[5: estacion_id=sint-sur-01, temporada=2022-2023].calor.calidad_dato.version_calculo: antes 'rachas-v1_35c_min5_temporada', ahora 'dias_umbral-v2_35c_1001-0430'
$.ficha_temporada[6: estacion_id=sint-sur-01, temporada=2023-2024].calor.calidad_dato.completitud_pct: antes 85.0, ahora 74.2
$.ficha_temporada[6: estacion_id=sint-sur-01, temporada=2023-2024].calor.calidad_dato.confiable: antes True, ahora False
$.ficha_temporada[6: estacion_id=sint-sur-01, temporada=2023-2024].calor.calidad_dato.version_calculo: antes 'rachas-v1_35c_min5_temporada', ahora 'dias_umbral-v2_35c_1001-0430'
$.ficha_temporada[7: estacion_id=sint-sur-01, temporada=2024-2025].calor.calidad_dato.version_calculo: antes 'rachas-v1_35c_min5_temporada', ahora 'dias_umbral-v2_35c_1001-0430'
```
