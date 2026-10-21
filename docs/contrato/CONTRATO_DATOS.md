# Contrato de datos backend ↔ frontend

## 0. Qué pueden mostrar hoy y qué llega después

| Disponible              | Bloques                                                            | Pantallas sugeridas                                                              | Archivo de ejemplo        |
| ----------------------- | ------------------------------------------------------------------ | -------------------------------------------------------------------------------- | ------------------------- |
| **Ya (Sprint 1)**       | Consolidación, estaciones, temporadas, completitud, resumen diario | Estado de los datos · Serie diaria de temperatura y lluvia · Mapa de completitud | `ejemplo_sprint1.json`    |
| 3 de octubre (Sprint 2) | Winkler, Huglin, rachas, días críticos, lluvia invernal            | Ficha del año · Detalle de calor                                                 | `ejemplo_resultados.json` |
| 7 de octubre (Sprint 3) | Clasificación de temporada y comparación entre años                | Comparación entre años                                                           | `ejemplo_resultados.json` |
| 17–19 de octubre (Sprint 5) | Mapa de calor (NDVI por predio) y coordenadas de estaciones     | Mapa satelital con la capa del predio y un marcador por estación                 | `ejemplo_mapa_calor.json` |

**Recomendación para el frontend:** construir primero las pantallas del Sprint 1 con `ejemplo_sprint1.json`. Responden la primera pregunta del cliente —_¿nuestros datos sirven?_— y son las únicas que pueden mostrar datos reales antes del 3 de octubre.

## 1. Reglas generales

- Formato: JSON, codificación UTF-8.
- Base de la API: `/api/v1/`. Solo lectura (`GET`) para la demo; sin autenticación en esta versión.
- Fechas: `YYYY-MM-DD`, en hora de Chile. Fecha-hora: ISO 8601 con zona de Chile (`2026-01-15T14:00:00-03:00`).
- Nombres de campos: `snake_case`, en español y sin tildes.
- Números: punto decimal. Unidades en la §4.6.
- **Dato faltante = `null`**. Nunca se rellena con 0 ni con un valor estimado. El frontend lo muestra como "sin dato" (en gráficos: un hueco en la línea, no una caída a cero).
- **Temporada agrícola:** va del 1 de julio al 30 de junio y se identifica como `"2023-2024"` (la vendimia ocurre en el segundo año). _El día de corte está por confirmar con el enólogo; si cambia, cambian los valores pero no la forma del contrato._
- Todo bloque que entregue un índice o métrica incluye el objeto `calidad_dato` (§3).

## 2. Estaciones

Datos tomados de los Excel entregados por el cliente. Los campos marcados _por confirmar_ no aparecen en los Excel y los define el PO con el cliente; el frontend no debe dejar estos textos fijos en la pantalla, sino leerlos de `/estaciones`.

| `id`                 | `nombre`     | `subzona`      | `propietario`               | Localidad según el Excel                                                  | Datos desde |
| -------------------- | ------------ | -------------- | --------------------------- | ------------------------------------------------------------------------- | ----------- |
| `cp-cauquenes-01`    | El Arenal    | `cauquenes`    | Agropacal _(por confirmar)_ | "HUERTO: EL ARENAL, AGROPACAL" · "LOCALIDAD: CAUQUENES, REGIÓN DEL MAULE" | 2021-08-01  |
| `cp-san-clemente-01` | San Clemente | `san-clemente` | `null` _(por confirmar)_    | "LOCALIDAD: SAN CLEMENTE, REGIÓN DEL MAULE"                               | 2020-01-01  |

Hoy hay una estación por subzona. Si se agregan zonas, llegan como estaciones nuevas en `/estaciones`, sin cambiar el contrato.

## 3. Endpoints

| #   | Endpoint                                                                     | Qué entrega                                                  | Sprint |
| --- | ---------------------------------------------------------------------------- | ------------------------------------------------------------ | ------ |
| 1   | `GET /api/v1/consolidacion`                                                  | Resultado de la última carga de cada Excel                   | **1**  |
| 2   | `GET /api/v1/estaciones`                                                     | Estaciones, variables y completitud global                   | **1**  |
| 3   | `GET /api/v1/temporadas`                                                     | Temporadas con datos                                         | **1**  |
| 4   | `GET /api/v1/completitud?estacion={id}`                                      | Completitud por temporada y variable (sin `estacion`, todas) | **1**  |
| 5   | `GET /api/v1/resumen-diario?estacion={id}&desde=AAAA-MM-DD&hasta=AAAA-MM-DD` | Valores diarios                                              | **1**  |
| 6   | `GET /api/v1/temporadas/{temporada}?estacion={id}`                           | Índices, clasificación y días críticos                       | 2 y 3  |
| 7   | `GET /api/v1/rachas/{temporada}?estacion={id}`                               | Rachas de días sobre el umbral                               | 2      |
| 8   | `GET /api/v1/comparacion?estacion={id}`                                      | Temporadas lado a lado y diferencia contra el promedio       | 3      |

Mientras la API no esté desplegada (D4.2), cada endpoint corresponde a una clave del archivo de ejemplo (`consolidacion`, `estaciones`, `temporadas`, `completitud_por_temporada`, `resumen_diario`, `ficha_temporada`, `rachas`, `comparacion`).

El archivo con datos reales lo genera `python manage.py exportar_json` (E1C-48). Ahí `resumen_diario` trae un elemento por estación, y `ficha_temporada` y `rachas` uno por estación y temporada. Además incluye `generado` (fecha del archivo) y `temporada_en_curso`. Por ahora no incluye `consolidacion` ni `comparacion`. Suma `mapa_calor` (§5.4): una entrada por estación, en el mismo orden que `estaciones`.

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

| Campo                    | Tipo                                   | Descripción                                                                                                                                                  |
| ------------------------ | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `completitud_pct`        | número 0–100                           | % de días (u horas, con datos horarios) con dato válido en el período                                                                                        |
| `confiable`              | booleano                               | `false` si la completitud está bajo el umbral. **El frontend debe mostrar una advertencia visible.**                                                         |
| `umbral_completitud_pct` | número                                 | Umbral usado para decidir `confiable` (80 por defecto)                                                                                                       |
| `resolucion_origen`      | `"diaria"` \| `"horaria"` \| `"mixta"` | Hoy los Excel traen promedios diarios. Cuando lleguen datos horarios cambia el valor, no el contrato. `"mixta"`: la estación tiene períodos de los dos tipos |
| `version_calculo`        | texto o `null`                         | Fórmula y parámetros usados. `null` en bloques que no calculan índices                                                                                       |

---

## 4. Bloques del Sprint 1 — disponibles ya

### 4.1 Consolidación (`/consolidacion`)

Qué se cargó, qué se rechazó y qué se descartó. Sirve para una pantalla de "estado de los datos".

| Campo                  | Tipo       | Descripción                                                           |
| ---------------------- | ---------- | --------------------------------------------------------------------- |
| `fecha_ejecucion`      | fecha-hora | Cuándo corrió la última carga                                         |
| `resolucion_origen`    | texto      | `"diaria"` hoy                                                        |
| `archivos`             | lista      | Una entrada por Excel (hoy son 13, uno por estación y año). Ver abajo |
| `columnas_descartadas` | lista      | `columna` y `motivo` (datos de abejas, fuera de alcance)              |
| `valores_nulos`        | objeto     | `total` de mediciones sin valor y `motivo`                            |

Cada elemento de `archivos`:

| Campo                                                   | Tipo   | Descripción                                                                                                                                                                |
| ------------------------------------------------------- | ------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `archivo`                                               | texto  | Nombre del Excel (`"El Arenal 2024.xlsx"`)                                                                                                                                 |
| `estacion_id`                                           | texto  | Estación (§2)                                                                                                                                                              |
| `temporada_archivo`                                     | número | Año con que el cliente rotula el archivo (`2024`). El archivo 2024 trae de enero de 2024 a abril de 2025: **no es la temporada agrícola**                                  |
| `formato`                                               | texto  | `"A"` (Excel 2020–2022) o `"B"` (Excel 2023–2026)                                                                                                                          |
| `filas_leidas` / `filas_aceptadas` / `filas_rechazadas` | número | Conteo de filas                                                                                                                                                            |
| `motivos_rechazo`                                       | lista  | `motivo` y `filas`. Motivos posibles: `"Fecha inválida"` (filas vacías o de resumen del Excel), `"Fecha repetida en el archivo"`, `"Fecha futura o sin datos posteriores"` |

### 4.2 Estaciones (`/estaciones`)

| Campo                        | Tipo           | Descripción                                                                       |
| ---------------------------- | -------------- | --------------------------------------------------------------------------------- |
| `id`                         | texto          | Identificador de la estación (§2)                                                 |
| `nombre`                     | texto          | Nombre visible                                                                    |
| `subzona`                    | texto          | `cauquenes` \| `san-clemente`                                                     |
| `propietario`                | texto o `null` | Dueño de la estación. `null` si no está confirmado                                |
| `latitud`                    | número o `null` | Grados decimales (WGS84), negativo al sur. `null` si la estación no tiene ubicación |
| `longitud`                   | número o `null` | Grados decimales (WGS84), negativo al oeste. `null` si la estación no tiene ubicación |
| `variables`                  | lista de texto | Códigos de la §4.6 disponibles para la estación                                   |
| `fecha_inicio` / `fecha_fin` | fecha          | Primer y último día **con dato**                                                  |
| `temporadas_disponibles`     | número         | Temporadas con algún dato                                                         |
| `calidad_dato`               | objeto         | Ver §3. `completitud_pct` es la de Tmáx y Tmín entre `fecha_inicio` y `fecha_fin` |

**Marcador en el mapa:** se pone solo si `latitud` y `longitud` son distintas de `null`. Las coordenadas son aproximadas: vienen de la ubicación de las planillas del cliente, con precisión de 1 minuto (1 a 2 km), y no sirven para medir distancias. Una vez cargado `config/areas_mapa.json` con `cargar_areas_mapa`, San Clemente tiene las dos coordenadas. El Arenal no tiene ubicación: su `longitud` es `null` y su `latitud` es una aproximación heredada, así que no lleva marcador. El marcador muestra el último dato de la estación: el último elemento de `dias` de su `resumen_diario` (§4.5), que se une por `estacion_id`.

**Próxima versión:** se agregará `observaciones` (lista de texto) con notas sobre la fuente, por ejemplo cuando una variable viene de otra estación. Hoy `variables` lista solo las 4 del resumen diario; humedad, radiación y viento se sumarán cuando se agreguen al resumen.

### 4.3 Temporadas (`/temporadas`)

Lista de texto, de la más antigua a la más reciente. Alimenta el selector de año. Con los datos actuales: de `"2019-2020"` a `"2026-2027"`.

### 4.4 Completitud por temporada (`/completitud`)

| Campo         | Tipo             | Descripción                                                                            |
| ------------- | ---------------- | -------------------------------------------------------------------------------------- |
| `estacion_id` | texto            | Estación                                                                               |
| `temporada`   | texto            | Temporada agrícola                                                                     |
| `variables`   | objeto           | % de completitud por variable: `tmax`, `tmin`, `tmedia`, `precipitacion`               |
| `confiable`   | booleano         | Se decide por la **temperatura**: `tmax` y `tmin` ≥ umbral. La precipitación no decide |
| `observacion` | texto (opcional) | Nota cuando una variable no tiene datos en la temporada                                |

Reglas de cálculo:

- % = días con dato / días de la temporada. Si la temporada está en curso, se cuentan los días hasta hoy.
- Las temporadas en los extremos salen incompletas y, por lo tanto, no confiables (hoy: 2019-2020 y 2026-2027 en San Clemente; 2020-2021 y 2026-2027 en El Arenal). Es correcto: la pantalla debe mostrarlo, no esconderlo.
- Hoy `observacion` solo se entrega cuando falta toda la precipitación, con el texto `"sin datos de precipitación en la temporada"`.

Uso sugerido: tabla o mapa de calor estación × temporada, en verde, amarillo o rojo según la completitud.

### 4.5 Resumen diario (`/resumen-diario`)

| Campo             | Tipo  | Descripción                                                                                                                          |
| ----------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------ |
| `estacion_id`     | texto | Estación                                                                                                                             |
| `desde` / `hasta` | fecha | Rango consultado                                                                                                                     |
| `dias`            | lista | Por día: `fecha`, `tmax`, `tmin`, `tmedia`, `amplitud`, `precipitacion`; y `motivo_nulo` **solo** cuando el día no tiene temperatura |

Uso sugerido: gráfico de líneas con Tmáx, Tmín y Tmedia, barras de lluvia en un gráfico aparte, y una línea horizontal en 35 °C como referencia del umbral de estrés.

### 4.6 Variables

| Código          | Nombre visible              | Unidad | Origen                   | En `resumen_diario` |
| --------------- | --------------------------- | ------ | ------------------------ | ------------------- |
| `tmax`          | Temperatura máxima          | °C     | Excel                    | Sí                  |
| `tmin`          | Temperatura mínima          | °C     | Excel                    | Sí                  |
| `tmedia`        | Temperatura media           | °C     | Excel                    | Sí                  |
| `amplitud`      | Amplitud térmica            | °C     | Calculada: `tmax − tmin` | Sí                  |
| `precipitacion` | Precipitación diaria        | mm     | Excel                    | Sí                  |
| `humedad`       | Humedad relativa media      | %      | Excel                    | Próxima versión     |
| `radiacion`     | Radiación máxima            | W/m²   | Excel                    | Próxima versión     |
| `viento`        | Velocidad máxima del viento | m/s    | Excel                    | Próxima versión     |

Humedad, radiación y viento ya están cargadas en la base, pero todavía no salen en el resumen diario. Cuando se agreguen llegarán como campos nuevos de cada día, sin romper nada.

No disponibles con los datos actuales: valores horarios e intensidad horaria de lluvia. Llegarán cuando el cliente entregue datos horarios.

### 4.7 Notas sobre los datos reales

- **El Arenal** tiene datos desde el 1 de agosto de 2021. De enero a julio de 2021 su Excel viene vacío.
- **El Arenal 2026:** según nota del propio Excel, la humedad y la radiación de esa temporada vienen de otra estación (Keule Villaseca). Se informará en `observaciones` de `/estaciones` (próxima versión).
- Los Excel de El Arenal 2022, 2023 y 2024 traen fechas repetidas y días faltantes. Esas filas se rechazan y quedan en `/consolidacion`; esos días aparecen sin dato.

---

## 5. Bloques de los Sprints 2, 3 y 5 — llegan después

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
| `lluvia_fuera_invierno` | objeto | Lluvia del año agrícola, septiembre, crecimiento, etapas, días intensos y meses inusuales; calidad por ventana |
| `calor` | objeto | `dias_sobre_umbral`, `umbral_c`, `rachas_con_incidencia`, `racha_maxima_dias` |
| `clasificacion` | objeto o `null` | `termica` (`calida` \| `normal` \| `fria`), `hidrica` (`lluviosa` \| `normal` \| `seca`), `criterio` (regla numérica usada). Viene `null` solo si no se puede clasificar ningún eje; si falta uno, ese eje viene `null` y se explica en `motivo_nulo`. Incluye `en_curso` y `parcial_hasta`. |
| `dias_criticos` | lista | Máximo 10 elementos: `fecha`, `tmax`, de mayor a menor |

Parámetros de Winkler, Huglin y del período de acumulación: por confirmar con el enólogo. El valor usado queda en `version_calculo`.

#### Lluvia fuera del invierno

`lluvia_fuera_invierno` es informativo y no modifica la clasificación, que continúa usando la lluvia de mayo a agosto.

- `total_anio_agricola_mm`: acumulado entre el 1 de mayo y el 30 de abril siguiente.
- `septiembre_mm`: acumulado de septiembre.
- `crecimiento_mm`: acumulado entre el 1 de octubre y el 30 de abril.
- `etapas`: brotación y floración (`brotacion_floracion`, 1-oct a 30-nov), cuaja a envero (`cuaja_envero`, 1-dic a 31-ene) y maduración y cosecha (`maduracion_cosecha`, 1-feb a 30-abr). Cada etapa incluye `desde`, `hasta`, `mm`, `promedio_mm`, `diferencia_pct`, `temporadas_en_promedio`, `en_curso` y `evaluado_hasta`. Si la etapa está en curso, el promedio histórico se corta al mismo día y mes; `diferencia_pct` queda `null` si los datos no son confiables o el promedio es cero/no disponible.
- `dias_lluvia_intensa`: días de crecimiento con precipitación diaria igual o superior a `UMBRAL_LLUVIA_INTENSA_MM` (10 mm por defecto, referencia R10mm del ETCCDI); cada registro indica `fecha`, `mm` y `etapa`.
- `meses_inusuales`: meses de octubre a abril con al menos `UMBRAL_LLUVIA_INTENSA_MM` (10 mm por defecto) y un acumulado igual o superior a `FACTOR_MES_INUSUAL` (2 por defecto) veces el promedio de ese mes en la estación. `mes` usa formato `AAAA-MM`. El promedio incluye la temporada evaluada si el mes ya terminó, y solo temporadas terminadas y confiables. Se requieren al menos `MIN_TEMPORADAS_PROMEDIO` (2) para publicar promedio y alerta; se entrega `temporadas_en_promedio`.
- Los promedios de etapas aplican la misma regla: temporadas terminadas y confiables, incluida la evaluada si terminó, con un mínimo de `MIN_TEMPORADAS_PROMEDIO` (2). Cada etapa informa `temporadas_en_promedio`.
- `calidad_dato`: conserva los campos comunes (§3), agrega `en_curso` y `evaluado_hasta`. `completitud_pct` es la menor completitud entre las ventanas iniciadas; las ventanas futuras no afectan el resultado global. `confiable` es `true` solo si todas las ventanas iniciadas alcanzan el umbral global. `ventanas` desglosa la calidad para el año agrícola, septiembre, crecimiento y cada etapa.
- Si `total_anio_agricola_mm` es `null`, se entrega `motivo_nulo`. Un día intenso que quede fuera de las etapas configuradas se omite; no hace fallar la ficha.

Las ventanas de una temporada en curso se evalúan hasta la fecha local actual. Para comparar una etapa en curso, cada temporada histórica se corta al mismo día y mes; el 29 de febrero se ajusta al 28 en años no bisiestos. Las fechas fenológicas son provisionales y deben confirmarse con el enólogo.

### 5.2 Rachas de calor (`/rachas/{temporada}`) — Sprint 2

| Campo                       | Tipo   | Descripción                                                         |
| --------------------------- | ------ | ------------------------------------------------------------------- |
| `temporada` / `estacion_id` | texto  | Temporada y estación consultadas                                    |
| `umbral_c`                  | número | Umbral de temperatura (35 °C por defecto)                           |
| `minimo_dias_incidencia`    | número | Días seguidos para considerar incidencia (5 por defecto)            |
| `rachas`                    | lista  | `inicio`, `fin`, `dias`, `tmax_maxima`, `con_incidencia` (booleano) |

### 5.3 Comparación entre años (`/comparacion`) — Sprint 3

| Campo                | Tipo           | Descripción                                                                                                                                                       |
| -------------------- | -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `estacion_id`        | texto          | Estación consultada                                                                                                                                               |
| `promedio_historico` | objeto         | Promedio de cada métrica entre las temporadas confiables                                                                                                          |
| `temporadas`         | lista          | Por temporada: `temporada`, `winkler`, `huglin`, `lluvia_invernal_mm`, `dias_sobre_35`, `clasificacion`, `diferencia_vs_promedio` (% por métrica), `calidad_dato` |
| `advertencia`        | texto o `null` | Por ejemplo, cuando hay pocas temporadas para concluir                                                                                                            |

### 5.4 Mapa de calor (`mapa_calor`) — Sprint 5

Capa de NDVI (índice de vigor de la vegetación, sin unidad) de cada predio, para pintarla sobre un mapa satelital. Va como clave de primer nivel `mapa_calor` del archivo de `exportar_json`: una lista con **una entrada por estación**, en el mismo orden que `estaciones`, con la imagen más reciente que tenga celdas válidas (sin histórico). Todavía no tiene endpoint.

**Estado:** `exportar_json` emite el bloque con las capas que guarda `actualizar_mapa_calor` (E1C-126). Hoy esa actualización es manual (`python manage.py actualizar_mapa_calor --estacion <codigo> --capa ndvi`), así que `fecha_imagen` muestra hasta cuándo llegó la última. Para construir sin esperar datos reales, el frontend puede usar `ejemplo_mapa_calor.json` (claves `estaciones` y `mapa_calor`): su grilla es **sintética**, pero la forma es la que emite el backend.

| Campo             | Tipo                                                    | Descripción                                                                                                                                                                                                  |
| ----------------- | ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `estacion_id`     | texto                                                   | Igual a `estaciones[].id` (§4.2)                                                                                                                                                                             |
| `capa`            | texto                                                   | Hoy solo `"ndvi"`                                                                                                                                                                                            |
| `fecha_imagen`    | fecha o `null`                                          | Día de captura de la escena Sentinel-2                                                                                                                                                                       |
| `limites`         | `[[lat_sur, lon_oeste], [lat_norte, lon_este]]` o `null` | Caja que contiene la grilla, en grados decimales (WGS84). Orden **[lat, lon]**, el que pide `L.imageOverlay`. El contorno GeoJSON de `config/areas_mapa.json` va al revés, en [lon, lat]. Ver «Alineación»   |
| `resolucion_m`    | número o `null`                                         | Tamaño de celda en metros (`10.0` con Sentinel-2)                                                                                                                                                            |
| `ancho`, `alto`   | entero o `null`                                         | Columnas y filas de la grilla                                                                                                                                                                                |
| `valores`         | lista de `alto` listas de `ancho` números o `null`      | Un valor de NDVI por celda. Ver «Grilla»                                                                                                                                                                     |
| `escala`          | objeto o `null`                                         | `minimo` y `maximo` del rango de la leyenda (0 y 1) y `paleta` sugerida (lista de colores `#rrggbb`, de menor a mayor valor)                                                                                 |
| `pct_validos`     | número 0–100 o `null`                                   | % de las celdas **dentro del predio** que tienen valor. Dice cuánto del predio se ve en la imagen                                                                                                            |
| `nubosidad_pct`   | número 0–100 o `null`                                   | % de nubes de la **escena completa** de Sentinel-2 (decenas de km), no del predio. Es un dato de contexto, independiente de `pct_validos`: con una escena despejada una nube puede tapar justo el predio      |
| `fuente`          | texto o `null`                                          | `"Sentinel-2 L2A (Copernicus Data Space)"`                                                                                                                                                                   |
| `atribucion`      | texto o `null`                                          | `"Contains modified Copernicus Sentinel data AAAA"`, con AAAA = año de `fecha_imagen`. **El frontend debe mostrarla** siempre que muestre la capa                                                             |
| `version_calculo` | texto o `null`                                          | Fórmula y parámetros usados, con el formato del resto del contrato. Hoy `"ndvi-sentinel-2-l2a-v1_scl-cloud-shadow_10m"`: NDVI = (B08 − B04) / (B08 + B04), sin valor en nube, sombra, nieve y píxeles sin dato |
| `motivo_nulo`     | texto (opcional)                                        | **Solo** cuando no hay imagen útil. Texto en español, listo para mostrar                                                                                                                                     |

#### Grilla

- `valores[0]` es la fila del **borde norte** y `valores[i][0]` la columna del **borde oeste**: se lee de arriba abajo y de izquierda a derecha, como una imagen. `len(valores)` es `alto` y cada fila tiene `ancho` elementos.
- `null` en una celda es **sin dato** (§1) y no distingue la causa: fuera del contorno del predio, nube, sombra o nieve. Se pinta transparente.
- El NDVI va de −1 a 1 y los valores van redondeados a 3 decimales. Un predio de unas 30 ha pesa cerca de 35 KB.
- `escala.minimo` y `escala.maximo` son un rango fijo de la capa (0 a 1), no el mínimo y máximo de esa imagen, para que los colores se puedan comparar entre fechas. Un valor puede quedar fuera del rango (el agua o el suelo desnudo dan NDVI negativo o cercano a 0): se pinta con el color de la punta.

#### Alineación con el mapa (limitación conocida)

La grilla se pide en UTM (hoy `EPSG:32719`, huso 19 sur): sus filas y columnas siguen la cuadrícula UTM, no el norte geográfico. `limites` es la caja en lat/lon que contiene esa grilla. A la latitud de San Clemente la cuadrícula queda girada cerca de 1,4° respecto del norte, de modo que al estirar la imagen sobre `limites` con `imageOverlay` cada punto puede quedar corrido hasta unos 15 a 20 m (1 o 2 celdas) en las esquinas y casi nada en el centro (estimado, no medido sobre una imagen real). Es del orden del error del contorno del predio (20–30 m) y no cambia la lectura del vigor, pero conviene tenerlo presente si se dibuja el contorno encima de la capa. La mejora está del lado del backend: pedir o reproyectar la grilla a lat/lon.

#### Sin imagen útil

La entrada mantiene su forma: trae `estacion_id`, `capa` y `motivo_nulo`, y **todos los demás campos en `null`**. Basta una condición: si `valores` es `null`, el frontend no pinta la capa y muestra `motivo_nulo`.

Una imagen es útil si tiene al menos una celda válida dentro del predio (`pct_validos` mayor que 0); se entrega la más reciente que lo cumple. No hay otro umbral de calidad: el cálculo de E1C-126 ya elige la escena menos nublada de los últimos 30 días. Los motivos de hoy, con su texto:

- «El predio aún no tiene ubicación ni contorno cargados.» Sin imagen y sin `longitud` (hoy El Arenal).
- «Aún no hay una imagen satelital con datos válidos para este predio.» Con ubicación, pero sin ninguna capa guardada o con todas sin celdas válidas.
- «La imagen guardada está incompleta; hay que volver a generarla.» La capa no trae sus límites geográficos.

#### Calidad del dato

A diferencia de los demás bloques, `mapa_calor` no lleva `calidad_dato` (§1 y §3): la cobertura de una imagen es espacial, no un porcentaje de días. La calidad se lee en `pct_validos` y `nubosidad_pct`; `version_calculo` sigue el mismo formato que en el resto del contrato.

#### Uso sugerido

Mapa base satelital con la grilla encima como imagen (`imageOverlay` de Leaflet), una leyenda con `escala` y, junto a ella, `fecha_imagen`, `pct_validos` y `atribucion`. Si `pct_validos` es bajo, conviene avisar que la imagen cubre solo una parte del predio. `leaflet.heat` está pensado para densidad de puntos, no para un valor continuo como el NDVI. La grilla se dibuja en un `canvas`:

```js
const { limites, ancho, alto, valores, escala } = entrada; // entrada con valores != null
const lienzo = document.createElement("canvas");
lienzo.width = ancho;
lienzo.height = alto;
const ctx = lienzo.getContext("2d");
const imagen = ctx.createImageData(ancho, alto);
valores.forEach((fila, y) =>
  fila.forEach((v, x) => {
    if (v === null) return; // sin dato: queda transparente
    const [r, g, b] = colorDe(v, escala); // interpola la paleta entre minimo y maximo
    imagen.data.set([r, g, b, 255], (y * ancho + x) * 4);
  }),
);
ctx.putImageData(imagen, 0, 0);
L.imageOverlay(lienzo.toDataURL(), limites, { opacity: 0.7 }).addTo(mapa);
```

`colorDe` es una función a escribir en el frontend. Si el mapa base es Esri World Imagery, hay que revisar sus términos de uso vigentes y mostrar su atribución, además de la de Copernicus.

#### Por confirmar

- _Con el frontend:_ la paleta definitiva, la opacidad de la capa y el mapa base.
- _Del lado del backend:_ alineación de la grilla con el norte (ver «Alineación»), actualización periódica de la capa y, si sobra tiempo, el endpoint `GET /api/v1/mapa-calor?estacion={codigo}` (hoy el bloque solo viaja en el JSON de `exportar_json`).

---

## 6. Estado de implementación en el backend

### E1C-17 — API de resultados (Sprint 3)

La implementación de E1C-46 y E1C-47 publica los siguientes endpoints de solo lectura,
sin barra final, usando datos del backend:

- `GET /api/v1/estaciones`
- `GET /api/v1/temporadas`
- `GET /api/v1/temporadas/{temporada}?estacion={codigo}`
- `GET /api/v1/rachas/{temporada}?estacion={codigo}`

El cuerpo es directamente la lista u objeto del contrato; no se envuelve en las claves
`ficha_temporada` o `rachas` del archivo de ejemplo. OpenAPI está en `/api/schema/`
y la documentación interactiva en `/api/docs/`.

La comparación entre años y la publicación de consolidación, completitud
y resumen diario no forman parte de este cambio. Sus funciones internas
existentes siguen disponibles.

Precisiones de calidad para esta entrega:

- Winkler y Huglin se leen de `IndiceClimatico`; un GET no ejecuta sus cálculos.
  Si no existe un índice calculado, `valor`, su clasificación y la completitud del
  índice son `null`, `confiable` es `false` y se añade `motivo_nulo`.
- `calidad_dato` también se publica en `lluvia_invernal`, `calor` y el detalle de
  `rachas`, de acuerdo con la regla general de incluirlo en las métricas.
- `resolucion_origen` puede ser `null` si no hay registros de origen que permitan
  determinarla; no se supone que sean diarios. `version_calculo` es `null` cuando
  no hay un índice calculado. Para los índices existentes se conserva la versión
  guardada por el motor, sin reemplazarla por la del JSON ficticio.
- La completitud de los índices usa los días válidos/esperados guardados por el motor,
  en la ventana de cada índice. La de `calor` usa días con Tmáx sobre los días esperados entre el 1 de octubre y el 30 de abril, igual que `dias_sobre_umbral`; la del detalle de `rachas` usa la temporada completa. En ambos casos, hasta hoy (hora de Chile) si la temporada está en curso.
  Son porcentajes basados en resúmenes diarios: `resolucion_origen` informa si estos
  provienen de datos diarios, horarios o mixtos; no afirma una cobertura horaria.
- Se informa el umbral de completitud actualmente configurado. Un índice es confiable
  solo si el motor lo dejó confiable y además alcanza ese umbral. Bajar el umbral no
  cambia automáticamente un resultado antes no confiable; debe recalcularse el índice.
- Los valores observados iguales a cero se conservan. Sin temperatura, los conteos
  de calor son `null`; sin lluvia, `acumulado_mm` es `null`. En ambos casos se entrega
  `motivo_nulo`. Las listas de días críticos y rachas pueden estar vacías.
- Las rachas incluyen `interrumpida_por_dato_faltante`, para conservar la información
  que ya produce el motor y evitar interpretar una secuencia incompleta como cerrada.
- Una consulta mal formada devuelve HTTP 400; estación desconocida o temporada sin
  registros devuelve HTTP 404. Una temporada con filas pero variables faltantes devuelve
  HTTP 200 con nulos y metadatos. POST, PUT, PATCH y DELETE no están habilitados.

Estas precisiones y campos adicionales deben comunicarse al equipo de frontend antes
del merge, según el proceso del README. Los archivos de ejemplo existentes siguen
siendo ficticios y no se usan como fuente de respuestas.

Estado anterior y diferencias pendientes:

Para que el frontend sepa qué ya responde con datos reales (fuera de la API, que llega en D4.2):

| Bloque                      | Estado                                 | Diferencias conocidas con este contrato                                                                                                                                                                           |
| --------------------------- | -------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `estaciones`                | Publicado en la API                    | El catálogo de El Arenal puede conservar `cp-villavicencio-01` / `villavicencio`; su corrección sigue pendiente. Leer el código de `/estaciones`. `fecha_inicio` y `fecha_fin` ahora toman los extremos con datos. Suma `latitud` y `longitud` (E1C-127), `null` si la estación no tiene ubicación |
| `temporadas`                | Implementado                           | —                                                                                                                                                                                                                 |
| `completitud_por_temporada` | Implementado                           | —                                                                                                                                                                                                                 |
| `resumen_diario`            | Implementado                           | Los días que el Excel no trae se omiten en vez de venir con `null` y motivo                                                                                                                                       |
| `consolidacion`             | Datos guardados, falta armar el bloque | `columnas_descartadas` se guarda como texto                                                                                                                                                                       |
| `mapa_calor`                | Publicado en el JSON de `exportar_json` | Sin endpoint. La capa se actualiza a mano con `actualizar_mapa_calor`. `ejemplo_mapa_calor.json` es sintético y no se usa como fuente de respuestas |


## E1C-124 · JSON de predicción ficticia de California

Este contrato es independiente de la ficha de temporadas de VIGNO. No cambia
fechas de hemisferio ni agrega estaciones, temporadas, correlaciones, calidad
o años análogos que el entrenamiento no haya calculado.

```powershell
docker compose exec backend python manage.py entrenar_cosecha
docker compose exec backend python manage.py exportar_prediccion_ficticia
```

Entrada: `data/ficticio/prediccion_cosecha_california.json` de E1C-85.
Salida: `data/ficticio/prediccion_ficticia.json`, ignorada por Git.
No requiere scikit-learn para exportar un entrenamiento ya generado.
Si falta la entrada, el comando termina con:
`CommandError("Corre primero: python manage.py entrenar_cosecha")`.
Una entrada inválida o incompleta también produce un error: no se inventan
valores ni se sustituye por un ejemplo.

| Campo de salida | Tipo | Origen y significado |
| --- | --- | --- |
| `generado` | string ISO 8601 con zona | `timezone.now().isoformat()` al exportar. |
| `datos_ficticios` | boolean | `datos_ficticios` de la entrada; debe ser `true`. |
| `fuente.cita` | string | `fuente` de la entrada, referencia de Bai et al. |
| `fuente.url` | string | `dataset_url` de la entrada. |
| `convencion_fechas` | string | Identifica fechas originales de California, sin desplazamiento. |
| `modelo.version` | string | `version_modelo` del entrenamiento. |
| `modelo.variables` | array de strings | `features`, exactamente las usadas por el modelo. |
| `modelo.importancias` | objeto | `importancias_random_forest`, sin números prefijados. |
| `modelo.regresion_lineal` | objeto | Intercepto, coeficientes y nota originales. |
| `modelo.metricas` | objeto | Copia completa de `metricas`; MAE, RMSE y tamaño de muestra por método. |
| `modelo.comparacion_base` | objeto | Copia de `comparacion_base`: `rf_mejora_mae` y `rf_mejora_rmse`. |
| `modelo.validacion` | objeto | Años de entrenamiento/prueba, cantidades y exclusiones originales. |
| `predicciones` | array de objetos | Todas las filas de prueba, sin modificar identidades ni fechas. |
| `predicciones[].fuente/region/anio/cultivar/color` | string/string/integer/string/string | Identidad original del dataset de California. |
| `predicciones[].doy_real/doy_estimado/diferencia_dias` | number | DOY y error firmado calculados por E1C-85. |
| `predicciones[].fecha_real` | string YYYY-MM-DD | Fecha original del año de California. |
| `predicciones[].prediccion` | objeto | Centro, extremos y dispersión 10–90 de árboles calculados por E1C-85. |

Se conservan también los demás campos que produzca E1C-85 en cada fila,
por ejemplo las predicciones de regresión lineal y promedio regional.
Las métricas de Napa corresponden a E1C-87; este exportador no las simula.

La salida se escribe en UTF-8 sin BOM. Los tests usan `tmp_path` y
`settings.BASE_DIR`; nunca escriben en la carpeta real `data/cliente`.
No se versiona un JSON con resultados inventados: el ejemplo para el frontend
se obtiene ejecutando ambos comandos sobre el CSV local.


## Calidad del dato: integración E1C-71, E1C-70, E1C-68 y E1C-130

- `resumen_diario.dias[].motivo_nulo` es opcional y también puede aparecer
  en días con datos parciales. El frontend debe conservar los valores no
  nulos y mostrar el motivo; no debe ocultar todo el día ni convertir nulos
  en cero. Un motivo de lluvia no significa que las temperaturas sean inválidas.
- `ResumenDiario.confiable` conserva el criterio térmico existente: una
  precipitación marcada no cambia esa bandera. Una temperatura marcada sí
  la fuerza a false; esto no modifica los criterios de completitud por métrica.
- `/api/v1/calidad/fallas` es la ruta del reporte de calidad. Actualmente
  incluye `fuera_de_rango`; E1C-70 agrega rechazados, nulos y días sin
  registro en esa misma ruta. `tipos_incluidos` indica los tipos disponibles.
- E1C-68 debe asignar a toda estación nueva un `codigo` único, no nulo y no
  vacío y devolverlo en POST/GET estaciones. E1C-130 usa ese código en el
  parámetro `estacion`; no utiliza el nombre ni el id numérico. La creación
  de estaciones nuevas pertenece a E1C-68, no a este ajuste.
