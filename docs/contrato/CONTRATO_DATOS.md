# Contrato de datos backend ↔ frontend 
## 0. Qué pueden mostrar hoy y qué llega después

| Disponible | Bloques | Pantallas sugeridas | Archivo de ejemplo |
|---|---|---|---|
| **Ya (Sprint 1)** | Consolidación, estaciones, temporadas, completitud, resumen diario | Estado de los datos · Serie diaria de temperatura y lluvia · Mapa de completitud | `ejemplo_sprint1.json` |
| 3 de octubre (Sprint 2) | Winkler, Huglin, rachas, días críticos, lluvia invernal | Ficha del año · Detalle de calor | `ejemplo_resultados.json` |
| 7 de octubre (Sprint 3) | Clasificación de temporada y comparación entre años | Comparación entre años | `ejemplo_resultados.json` |

**Recomendación para el frontend:** construir primero las pantallas del Sprint 1 con `ejemplo_sprint1.json`. Responden la primera pregunta del cliente —*¿nuestros datos sirven?*— y son las únicas que pueden mostrar datos reales antes del 3 de octubre.

## 1. Reglas generales

- Formato: JSON, codificación UTF-8.
- Base de la API: `/api/v1/`. Solo lectura (`GET`) para la demo; sin autenticación en esta versión.
- Fechas: `YYYY-MM-DD`, en hora de Chile. Fecha-hora: ISO 8601 con zona de Chile (`2026-01-15T14:00:00-03:00`).
- Nombres de campos: `snake_case`, en español y sin tildes.
- Números: punto decimal. Unidades en la §4.6.
- **Dato faltante = `null`**. Nunca se rellena con 0 ni con un valor estimado. El frontend lo muestra como "sin dato" (en gráficos: un hueco en la línea, no una caída a cero).
- **Temporada agrícola:** va del 1 de julio al 30 de junio y se identifica como `"2023-2024"` (la vendimia ocurre en el segundo año). *El día de corte está por confirmar con el enólogo; si cambia, cambian los valores pero no la forma del contrato.*
- Todo bloque que entregue un índice o métrica incluye el objeto `calidad_dato` (§3).

## 2. Estaciones

Datos tomados de los Excel entregados por el cliente. Los campos marcados *por confirmar* no aparecen en los Excel y los define el PO con el cliente; el frontend no debe dejar estos textos fijos en la pantalla, sino leerlos de `/estaciones`.

| `id` | `nombre` | `subzona` | `propietario` | Localidad según el Excel | Datos desde |
|---|---|---|---|---|---|
| `cp-cauquenes-01` | El Arenal | `cauquenes` | Agropacal *(por confirmar)* | "HUERTO: EL ARENAL, AGROPACAL" · "LOCALIDAD: CAUQUENES, REGIÓN DEL MAULE" | 2021-08-01 |
| `cp-san-clemente-01` | San Clemente | `san-clemente` | `null` *(por confirmar)* | "LOCALIDAD: SAN CLEMENTE, REGIÓN DEL MAULE" | 2020-01-01 |

Hoy hay una estación por subzona. Si se agregan zonas, llegan como estaciones nuevas en `/estaciones`, sin cambiar el contrato.

## 3. Endpoints

| # | Endpoint | Qué entrega | Sprint |
|---|---|---|---|
| 1 | `GET /api/v1/consolidacion` | Resultado de la última carga de cada Excel | **1** |
| 2 | `GET /api/v1/estaciones` | Estaciones, variables y completitud global | **1** |
| 3 | `GET /api/v1/temporadas` | Temporadas con datos | **1** |
| 4 | `GET /api/v1/completitud?estacion={id}` | Completitud por temporada y variable (sin `estacion`, todas) | **1** |
| 5 | `GET /api/v1/resumen-diario?estacion={id}&desde=AAAA-MM-DD&hasta=AAAA-MM-DD` | Valores diarios | **1** |
| 6 | `GET /api/v1/temporadas/{temporada}?estacion={id}` | Índices, clasificación y días críticos | 2 y 3 |
| 7 | `GET /api/v1/rachas/{temporada}?estacion={id}` | Rachas de días sobre el umbral | 2 |
| 8 | `GET /api/v1/comparacion?estacion={id}` | Temporadas lado a lado y diferencia contra el promedio | 3 |

Mientras la API no esté desplegada (D4.2), cada endpoint corresponde a una clave del archivo de ejemplo (`consolidacion`, `estaciones`, `temporadas`, `completitud_por_temporada`, `resumen_diario`, `ficha_temporada`, `rachas`, `comparacion`).

### Objeto `calidad_dato` (común)

```json
"calidad_dato": {
  "completitud_pct": 94.2,
  "confiable": true,
  "umbral_completitud_pct": 80,
  "resolucion_origen": "diaria",
  "version_calculo": "winkler-v1_base10_0110-3004"
}
```

| Campo | Tipo | Descripción |
|---|---|---|
| `completitud_pct` | número 0–100 | % de días (u horas, con datos horarios) con dato válido en el período |
| `confiable` | booleano | `false` si la completitud está bajo el umbral. **El frontend debe mostrar una advertencia visible.** |
| `umbral_completitud_pct` | número | Umbral usado para decidir `confiable` (80 por defecto) |
| `resolucion_origen` | `"diaria"` \| `"horaria"` \| `"mixta"` | Hoy los Excel traen promedios diarios. Cuando lleguen datos horarios cambia el valor, no el contrato. `"mixta"`: la estación tiene períodos de los dos tipos |
| `version_calculo` | texto o `null` | Fórmula y parámetros usados. `null` en bloques que no calculan índices |

---

## 4. Bloques del Sprint 1 — disponibles ya

### 4.1 Consolidación (`/consolidacion`)

Qué se cargó, qué se rechazó y qué se descartó. Sirve para una pantalla de "estado de los datos".

| Campo | Tipo | Descripción |
|---|---|---|
| `fecha_ejecucion` | fecha-hora | Cuándo corrió la última carga |
| `resolucion_origen` | texto | `"diaria"` hoy |
| `archivos` | lista | Una entrada por Excel (hoy son 13, uno por estación y año). Ver abajo |
| `columnas_descartadas` | lista | `columna` y `motivo` (datos de abejas, fuera de alcance) |
| `valores_nulos` | objeto | `total` de mediciones sin valor y `motivo` |

Cada elemento de `archivos`:

| Campo | Tipo | Descripción |
|---|---|---|
| `archivo` | texto | Nombre del Excel (`"El Arenal 2024.xlsx"`) |
| `estacion_id` | texto | Estación (§2) |
| `temporada_archivo` | número | Año con que el cliente rotula el archivo (`2024`). El archivo 2024 trae de enero de 2024 a abril de 2025: **no es la temporada agrícola** |
| `formato` | texto | `"A"` (Excel 2020–2022) o `"B"` (Excel 2023–2026) |
| `filas_leidas` / `filas_aceptadas` / `filas_rechazadas` | número | Conteo de filas |
| `motivos_rechazo` | lista | `motivo` y `filas`. Motivos posibles: `"Fecha inválida"` (filas vacías o de resumen del Excel), `"Fecha repetida en el archivo"`, `"Fecha futura o sin datos posteriores"` |

### 4.2 Estaciones (`/estaciones`)

| Campo | Tipo | Descripción |
|---|---|---|
| `id` | texto | Identificador de la estación (§2) |
| `nombre` | texto | Nombre visible |
| `subzona` | texto | `cauquenes` \| `san-clemente` |
| `propietario` | texto o `null` | Dueño de la estación. `null` si no está confirmado |
| `variables` | lista de texto | Códigos de la §4.6 disponibles para la estación |
| `fecha_inicio` / `fecha_fin` | fecha | Primer y último día **con dato** |
| `temporadas_disponibles` | número | Temporadas con algún dato |
| `calidad_dato` | objeto | Ver §3. `completitud_pct` es la de Tmáx y Tmín entre `fecha_inicio` y `fecha_fin` |

**Próxima versión:** se agregará `observaciones` (lista de texto) con notas sobre la fuente, por ejemplo cuando una variable viene de otra estación. Hoy `variables` lista solo las 4 del resumen diario; humedad, radiación y viento se sumarán cuando se agreguen al resumen.

### 4.3 Temporadas (`/temporadas`)

Lista de texto, de la más antigua a la más reciente. Alimenta el selector de año. Con los datos actuales: de `"2019-2020"` a `"2026-2027"`.

### 4.4 Completitud por temporada (`/completitud`)

| Campo | Tipo | Descripción |
|---|---|---|
| `estacion_id` | texto | Estación |
| `temporada` | texto | Temporada agrícola |
| `variables` | objeto | % de completitud por variable: `tmax`, `tmin`, `tmedia`, `precipitacion` |
| `confiable` | booleano | Se decide por la **temperatura**: `tmax` y `tmin` ≥ umbral. La precipitación no decide |
| `observacion` | texto (opcional) | Nota cuando una variable no tiene datos en la temporada |

Reglas de cálculo:
- % = días con dato / días de la temporada. Si la temporada está en curso, se cuentan los días hasta hoy.
- Las temporadas en los extremos salen incompletas y, por lo tanto, no confiables (hoy: 2019-2020 y 2026-2027 en San Clemente; 2020-2021 y 2026-2027 en El Arenal). Es correcto: la pantalla debe mostrarlo, no esconderlo.
- Hoy `observacion` solo se entrega cuando falta toda la precipitación, con el texto `"sin datos de precipitación en la temporada"`.

Uso sugerido: tabla o mapa de calor estación × temporada, en verde, amarillo o rojo según la completitud.

### 4.5 Resumen diario (`/resumen-diario`)

| Campo | Tipo | Descripción |
|---|---|---|
| `estacion_id` | texto | Estación |
| `desde` / `hasta` | fecha | Rango consultado |
| `dias` | lista | Por día: `fecha`, `tmax`, `tmin`, `tmedia`, `amplitud`, `precipitacion`; y `motivo_nulo` **solo** cuando el día no tiene temperatura |

Uso sugerido: gráfico de líneas con Tmáx, Tmín y Tmedia, barras de lluvia en un gráfico aparte, y una línea horizontal en 35 °C como referencia del umbral de estrés.

### 4.6 Variables

| Código | Nombre visible | Unidad | Origen | En `resumen_diario` |
|---|---|---|---|---|
| `tmax` | Temperatura máxima | °C | Excel | Sí |
| `tmin` | Temperatura mínima | °C | Excel | Sí |
| `tmedia` | Temperatura media | °C | Excel | Sí |
| `amplitud` | Amplitud térmica | °C | Calculada: `tmax − tmin` | Sí |
| `precipitacion` | Precipitación diaria | mm | Excel | Sí |
| `humedad` | Humedad relativa media | % | Excel | Próxima versión |
| `radiacion` | Radiación máxima | W/m² | Excel | Próxima versión |
| `viento` | Velocidad máxima del viento | m/s | Excel | Próxima versión |

Humedad, radiación y viento ya están cargadas en la base, pero todavía no salen en el resumen diario. Cuando se agreguen llegarán como campos nuevos de cada día, sin romper nada.

No disponibles con los datos actuales: valores horarios e intensidad horaria de lluvia. Llegarán cuando el cliente entregue datos horarios.

### 4.7 Notas sobre los datos reales

- **El Arenal** tiene datos desde el 1 de agosto de 2021. De enero a julio de 2021 su Excel viene vacío.
- **El Arenal 2026:** según nota del propio Excel, la humedad y la radiación de esa temporada vienen de otra estación (Keule Villaseca). Se informará en `observaciones` de `/estaciones` (próxima versión).
- Los Excel de El Arenal 2022, 2023 y 2024 traen fechas repetidas y días faltantes. Esas filas se rechazan y quedan en `/consolidacion`; esos días aparecen sin dato.

---

## 5. Bloques de los Sprints 2 y 3 — llegan después

### 5.1 Ficha de temporada (`/temporadas/{temporada}`) — Sprint 2 (índices) y 3 (clasificación)

| Campo | Tipo | Descripción |
|---|---|---|
| `temporada` | texto | `"2023-2024"` |
| `estacion_id` | texto | Estación consultada |
| `subzona` | texto | Subzona de la estación |
| `periodo` | objeto | `inicio` y `fin` de acumulación de los índices |
| `indices.winkler` | objeto | `valor`, `region` (I–V), `calidad_dato` |
| `indices.huglin` | objeto | `valor`, `clasificacion`, `calidad_dato` |
| `lluvia_invernal` | objeto | `acumulado_mm`, `promedio_historico_mm`, `diferencia_pct` |
| `calor` | objeto | `dias_sobre_umbral`, `umbral_c`, `rachas_con_incidencia`, `racha_maxima_dias` |
| `clasificacion` | objeto o `null` | `termica` (`calida` \| `normal` \| `fria`), `hidrica` (`lluviosa` \| `normal` \| `seca`), `criterio` (regla numérica usada). **Llega en el Sprint 3; antes viene `null`** |
| `dias_criticos` | lista | Máximo 10 elementos: `fecha`, `tmax`, de mayor a menor |

Parámetros de Winkler, Huglin y del período de acumulación: por confirmar con el enólogo. El valor usado queda en `version_calculo`.

### 5.2 Rachas de calor (`/rachas/{temporada}`) — Sprint 2

| Campo | Tipo | Descripción |
|---|---|---|
| `temporada` / `estacion_id` | texto | Temporada y estación consultadas |
| `umbral_c` | número | Umbral de temperatura (35 °C por defecto) |
| `minimo_dias_incidencia` | número | Días seguidos para considerar incidencia (5 por defecto) |
| `rachas` | lista | `inicio`, `fin`, `dias`, `tmax_maxima`, `con_incidencia` (booleano) |

### 5.3 Comparación entre años (`/comparacion`) — Sprint 3

| Campo | Tipo | Descripción |
|---|---|---|
| `estacion_id` | texto | Estación consultada |
| `promedio_historico` | objeto | Promedio de cada métrica entre las temporadas confiables |
| `temporadas` | lista | Por temporada: `temporada`, `winkler`, `huglin`, `lluvia_invernal_mm`, `dias_sobre_35`, `clasificacion`, `diferencia_vs_promedio` (% por métrica), `calidad_dato` |
| `advertencia` | texto o `null` | Por ejemplo, cuando hay pocas temporadas para concluir |

---

## 6. Estado de implementación en el backend

Para que el frontend sepa qué ya responde con datos reales (fuera de la API, que llega en D4.2):

| Bloque | Estado | Diferencias conocidas con este contrato |
|---|---|---|
| `estaciones` | Implementado | El catálogo de El Arenal tiene hoy `cp-villavicencio-01` / `villavicencio`; se corrige a lo de la §2. `fecha_inicio` hoy toma el primer día cargado, aunque esté vacío |
| `temporadas` | Implementado | — |
| `completitud_por_temporada` | Implementado | — |
| `resumen_diario` | Implementado | Los días que el Excel no trae se omiten en vez de venir con `null` y motivo |
| `consolidacion` | Datos guardados, falta armar el bloque | `columnas_descartadas` se guarda como texto |
