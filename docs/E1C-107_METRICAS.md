# E1C-107 · Motor compartido de métricas

Subtareas E1C-120 y E1C-121. Base: `refactor`, commit `2399dbc`.
E1C-105 y E1C-106 ya están integradas en esa base.

## Responsabilidades

`apps/clima/metricas.py` es el lugar común para Winkler, Huglin, días sobre
umbral y lluvia invernal. Define `METRICAS`, `valor_metrica`, los aportes diarios,
los factores y clasificaciones de los índices, y `calidad_metrica`.
Consulta resúmenes diarios y no escribe en la base.

Las ventanas se importan de `temporadas.py`; no se copian sus fechas en los
consumidores. Winkler y días de calor usan octubre–abril, Huglin octubre–marzo,
y lluvia invernal mayo–agosto. Se filtra por fecha: mayo–junio no pertenecen a la
misma etiqueta julio–junio que el resto del invierno.

| Consumidor | Responsabilidad después del cambio |
|---|---|
| `indices.py` | Guarda en `IndiceClimatico` los defaults del motor; sin fórmulas propias |
| `comparacion.py` | Decide cortes comparables y presenta diferencias entre temporadas |
| `clasificacion.py` | Usa las métricas compartidas para construir su referencia histórica |
| `resultados.py` | Presenta resultados y usa la calidad y los días de calor del motor |
| `lluvia.py` | Delega el acumulado invernal; conserva eventos horarios y comparación histórica |
| `dias_criticos.py` | Conserva el listado de días críticos y reexporta el guardado de días de calor |

No se cambia el esquema de base, el cálculo de rachas ni el módulo de lluvia
fuera de invierno. No se reincorpora el módulo de correlaciones archivado.

## Contrato interno

```python
valor_metrica(estacion, metrica, temporada, corte=None, umbral=None, *, para_guardar=False)
```

- `metrica`: `winkler`, `huglin`, `dias_sobre_umbral` o `lluvia_invernal`.
- `corte=None` evalúa la ventana completa, como hace el pipeline al guardar.
  Comparación, ficha de calor y lluvia proporcionan el corte que corresponda.
- `umbral` es el porcentaje mínimo de completitud. Si se omite, se lee
  `ConfiguracionCalidad`; un cero explícito no se sustituye por el valor por defecto.
- `para_guardar=False` devuelve el contrato previo de comparación: `valor`,
  `dias_con_dato`, `dias_esperados`, `completitud_pct`, `confiable` y `hasta`.
- `para_guardar=True` devuelve los campos necesarios para persistir: valor,
  conteos, confiabilidad, parámetros, clasificación y versión. No escribe.
- `valor=None` significa ausencia; `0` es un valor observado. El pipeline
  conserva su política de no guardar nuevos índices sin datos. Como antes,
  no elimina automáticamente índices antiguos si se retiraron todos sus datos.

Se conservan como reexportaciones los imports antiguos de aportes, factores y
clasificaciones desde `indices.py`, y de `valor_metrica`/`METRICAS` desde
`comparacion.py`. La implementación existe solo en `metricas.py`.

## Cambios de comportamiento que debe revisar el equipo

1. Días de calor: conteo y completitud usan octubre–abril. Antes el pipeline y
   la ficha contaban julio–junio, mientras la comparación usaba octubre–abril.
   La fuente del umbral es siempre `settings.UMBRAL_CALOR_C`. Se retira el
   argumento `umbral=` de `calcular_dias_sobre_umbral`; los tests usan
   `override_settings` o el fixture `settings` para cambiarlo.
2. La calidad de `ficha_temporada.calor` describe la ventana de días de calor,
   con versión `dias_umbral-v2_<umbral>c_1001-0430`. El recurso de rachas y los
   campos de rachas dentro de la ficha conservan su alcance anual. Sus medidas
   no tienen que coincidir con el conteo de octubre–abril.
3. La calidad compartida exige al menos un dato, también con umbral 0. La
   confiabilidad se decide con el porcentaje sin redondear; el porcentaje
   mostrado lleva un decimal. Así se evita promover, por ejemplo, 79,96% a 80%.
   Los antiguos caminos de comparación/lluvia redondeaban antes de decidir.
4. Lluvia en curso: el corte se aplica tanto al acumulado como al conteo y al
   denominador. Un dato posterior a ese corte no se suma aunque esté cargado.
   Esto alinea lluvia con comparación; antes el acumulado invernal podía sumar
   filas posteriores a hoy aunque su denominador solo llegara hasta hoy.

Los puntos 3 y 4 tienen pruebas de borde. No producen diferencias en el JSON
sintético de referencia. Las diferencias reales de esa referencia se enumeran
en [E1C-107_DIFERENCIAS_JSON.md](E1C-107_DIFERENCIAS_JSON.md): **17, todas en calor**.
El JSON actualizado es una propuesta explícita que el equipo debe revisar
antes del merge. No afirmar que la referencia original es idéntica.

Tras integrar, ejecutar el comando existente `calcular_indices` para actualizar
los registros persistidos de días de calor a la nueva versión. No hace falta
reingestar mediciones por esta tarea.

## Pruebas

```powershell
docker compose exec backend pytest
docker compose exec backend ruff check .
docker compose exec backend ruff format --check .
docker compose exec backend python manage.py check
docker compose exec backend python manage.py makemigrations --check --dry-run
```

Base sin cambios: 191 pruebas. Entrega final: 219 pruebas, todas correctas.
Las 28 nuevas cubren aportes, fallback, nulos/cero, límites de las ventanas,
umbral configurable, latitud ausente, bisiesto, corte futuro, aislamiento de
estaciones, ausencia de escrituras y coherencia entre consumidores.
El test del JSON final se ejecutó sin `REGENERAR_REFERENCIA` y sin omitirlo.
