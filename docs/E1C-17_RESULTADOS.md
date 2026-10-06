# E1C-17 Resultados y calidad de datos

Esta implementación cubre E1C-46 (endpoints de resultados) y E1C-47 (metadatos de
completitud y confiabilidad) en la rama `feat/e1c-17-resultados-calidad`, Sprint 3.
Reutiliza los cálculos del equipo y reúne sus resultados para el frontend.

## Archivos y responsabilidades

| Archivo | Función |
|---|---|
| `apps/clima/resultados.py` | Armar ficha de temporada y detalle de rachas con datos reales y calidad |
| `apps/clima/serializers.py` | Validar consultas, dar forma a respuestas y describir OpenAPI |
| `apps/clima/views.py` | Atender GET y devolver errores 400/404 cuando corresponda |
| `apps/clima/urls.py` y `vigno/urls.py` | Registrar las rutas `/api/v1/` |
| `apps/clima/models.py` | Leer el umbral sin crear configuración durante un GET |
| `apps/clima/services.py` | Usar fechas con datos en el catálogo de estaciones |
| `vigno/settings/base.py` | Configurar el umbral de calor y el mínimo de días de incidencia |
| `apps/clima/tests/test_api_resultados.py` | Probar contrato, datos reales, nulos, calidad, aislamiento y errores |
| `apps/clima/tests/test_resumen_diario.py` | Ajustar la expectativa del catálogo al primer día con datos |
| `docs/contrato/CONTRATO_DATOS.md` | Documentar las respuestas, nulos y dependencias de esta entrega |

No cambia el esquema de tablas ni requiere nuevas migraciones.

## Flujo de los datos

1. La ingesta existente carga las mediciones.
2. `generar_resumenes` genera los resúmenes diarios.
3. `calcular_indices` guarda Winkler, Huglin y días sobre umbral.
4. Los endpoints leen los índices guardados y consultan los módulos de lluvia,
   rachas y días críticos para construir la respuesta.

Los GET no modifican registros ni sustituyen datos faltantes. Los tests utilizan
datos sintéticos creados por las pruebas; los endpoints consultan la base del entorno.

## Probar con Docker

Desde la raíz del repositorio:

```powershell
docker compose up -d --build
docker compose exec backend python manage.py check
docker compose exec backend pytest
docker compose exec backend ruff check apps/clima/resultados.py apps/clima/serializers.py apps/clima/views.py apps/clima/urls.py apps/clima/models.py apps/clima/services.py apps/clima/tests/test_api_resultados.py apps/clima/tests/test_resumen_diario.py vigno/urls.py vigno/settings/base.py
docker compose exec backend python manage.py spectacular --validate --fail-on-warn --file /tmp/e1c17-schema.yml
docker compose exec backend python manage.py makemigrations --check --dry-run
```

El último comando comprueba que no faltan migraciones, sin crearlas.

Con mediciones ya cargadas y cuando sea necesario actualizar resultados:

```powershell
docker compose exec backend python manage.py generar_resumenes
docker compose exec backend python manage.py calcular_indices
```

Estos dos comandos sí actualizan datos derivados; ejecutarlos después de nuevas
cargas o cambios de configuración. No cargan archivos Excel por sí solos.

## Consultas manuales

```powershell
Invoke-RestMethod 'http://localhost:8000/api/health/'
Invoke-RestMethod 'http://localhost:8000/api/v1/estaciones' | ConvertTo-Json -Depth 10
Invoke-RestMethod 'http://localhost:8000/api/v1/temporadas' | ConvertTo-Json
```

Usar un código devuelto por estaciones y una temporada con datos para esa estación.
Ejemplo, únicamente si estos valores aparecen en el entorno:

```powershell
Invoke-RestMethod 'http://localhost:8000/api/v1/temporadas/2024-2025?estacion=cp-san-clemente-01' | ConvertTo-Json -Depth 10
Invoke-RestMethod 'http://localhost:8000/api/v1/rachas/2024-2025?estacion=cp-san-clemente-01' | ConvertTo-Json -Depth 10
```

También se pueden probar en `http://localhost:8000/api/docs/`.

## Reglas de calidad

- El 80 % es el valor predeterminado de `ConfiguracionCalidad.umbral_pct`.
  Se respeta el valor que tenga la base de datos, incluso si es cero.
- Los índices conservan su versión de cálculo y su indicador de confiabilidad.
  La respuesta además comprueba el umbral actual; no vuelve confiable un resultado
  que el motor rechazó, por ejemplo Huglin sin latitud.
- El porcentaje se muestra con un decimal; decidir confiabilidad de los índices
  usa la proporción sin redondear.
- Sin índice calculado: valor, clasificación, versión y completitud del índice
  son `null`, acompañado de `motivo_nulo` y `confiable: false`.
- Con datos parciales: se conserva el resultado calculado y se muestra su calidad.
- Sin temperaturas máximas: los conteos de calor son `null`, no cero.
- Sin lluvia: acumulado `null`. Si hubo mediciones de lluvia igual a cero, se devuelve cero.
- Los promedios de lluvia siguen el módulo existente: mínimo de dos inviernos
  terminados y confiables. La diferencia puede ser `null` aunque exista un acumulado.

El calor se calcula sobre la temporada agrícola completa del contrato; Winkler,
Huglin y lluvia conservan sus ventanas específicas. No se cambia la fórmula ni
la ventana de los módulos de cálculo.

## Configuración de calor

Opcionalmente, se pueden definir en el `.env` local:

```dotenv
UMBRAL_CALOR_C=35
MINIMO_DIAS_INCIDENCIA=5
```

Los valores predeterminados son 35 °C y 5 días. El mínimo debe ser un entero positivo.
Tras cambiar variables del `.env`, recrear el backend para cargar el nuevo entorno:

```powershell
docker compose up -d --force-recreate backend
```

Ambos endpoints comparten estos parámetros. Los parámetros aparecen en las respuestas
y en la versión de la métrica de calor/rachas. La configuración aplica a la API;
el comando previo `calcular_indices` conserva el comportamiento del equipo.

## Dependencias para cerrar la historia

- E1C-18 debe entregar la clasificación térmica/hídrica. Hasta integrarla, se devuelve
  `clasificacion: null`; no se puede afirmar que toda E1C-17 está cerrada.
- E1C-48 y E1C-49 cubren entrega al frontend y correcciones de integración.
- E1C-101 cubre el despliegue accesible al frontend. Una URL local no cumple ese despliegue.
- El catálogo de El Arenal puede conservar un código distinto del ejemplo. El frontend
  debe usar el código real del catálogo; este cambio no renombra datos existentes.
- Consolidación, completitud, resumen diario y comparación no se publican como rutas
  nuevas en esta entrega; no se deben presentar como endpoints ya disponibles.
- Antes del merge, informar al frontend de los metadatos adicionales, los campos
  que permiten `null` y la advertencia de rachas interrumpidas por faltantes.

## Evidencia para las subtareas

E1C-46: ficha y rachas consultables por estación/temporada, lectura de índices reales,
errores 400/404, catálogos para seleccionar datos y esquema OpenAPI actualizado.

E1C-47: completitud, umbral, confiabilidad, resolución, versión de cálculo y tratamiento
de nulos comprobados por pruebas. Añadir al PR el resultado de las pruebas ejecutadas
en la rama y una consulta local de ejemplo, sin adjuntar datos reales del cliente.
