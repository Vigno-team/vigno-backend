# E1C-131 · Correcciones manuales

Permite incorporar un valor proporcionado por una persona y volver a calcular los resultados.
No rellena otros campos ni estima datos faltantes. El autor y el motivo son obligatorios y
quedan en la bitácora, incluso después de revertir o reemplazar la corrección.

## Configuración

Configurar `INGESTA_API_KEY` en el `.env` del entorno. Es la misma clave prevista para la
carga de Excel (E1C-66) y el alta de estaciones (E1C-68). Si está vacía, los endpoints de
correcciones rechazan el acceso. No se agrega una clave predeterminada al repositorio.

```powershell
docker compose exec backend python manage.py migrate
docker compose exec backend pytest apps/clima/tests/test_correcciones.py
```

Después de modificar el `.env` de desarrollo, recrear el servicio para que reciba la variable:
`docker compose up -d --force-recreate backend`.
En el despliegue se usa `deploy/.env`; después de actualizar el código hay que reconstruir
las imágenes. Su arranque aplica la migración automáticamente.

Los tres endpoints requieren `X-Api-Key`, incluida la lectura de la bitácora. La clave
autoriza la operación; el campo `autor` sigue siendo declarado por quien la usa hasta
integrar las cuentas personales de E1C-64. No es una identidad autenticada individualmente.

## Crear una corrección

`POST /api/v1/correcciones`, cuerpo JSON:

```json
{
  "estacion": "cp-san-clemente-01",
  "fecha": "2025-01-16",
  "variable": "tmedia",
  "frecuencia": "D",
  "valor_nuevo": 21.0,
  "motivo": "Planilla manual del predio, registro del 16 de enero",
  "autor": "Nombre de quien revisó el dato"
}
```

Es un ejemplo del formato: usar el código, fecha y valor que correspondan al registro
revisado. Para un dato horario, indicar `frecuencia: "H"` y `hora: "14:00:00"`.

| Campo | Regla |
| --- | --- |
| `estacion` | Código de una estación existente, entregado por `GET /api/v1/estaciones`. |
| `fecha` | Fecha local `AAAA-MM-DD`, dentro del período observado y no futura. |
| `hora` | Obligatoria para H; omitir para D. Hora local de `TIME_ZONE` (America/Santiago). |
| `variable` | `tmax`, `tmin`, `tmedia`, `precipitacion`, o sus nombres canónicos de ingesta. |
| `frecuencia` | `D` o `H`. No se introduce una frecuencia que desplace los datos existentes del día. |
| `valor_nuevo` | Número finito dentro del catálogo `config/rangos_variables.json`. No acepta null. |
| `motivo` | Texto obligatorio, hasta 1.000 caracteres, indicando de dónde sale el dato. |
| `autor` | Texto obligatorio, hasta 100 caracteres. |
| `carga_origen`, `fila_origen` | Para corregir una fila rechazada: enviar ambas. La carga debe ser de la estación y la fila debe existir en sus rechazos. |

El período se obtiene de las primeras y últimas mediciones no nulas del Excel. Los valores
de borde que ya se corrigieron conservan su fecha original como evidencia. Una corrección
no extiende el histórico ni crea un período en una estación vacía.

Los diarios se guardan a las 12:00 locales, igual que la ingesta. No se admite una hora
ambigua o inexistente por cambio de horario. Para H tampoco se admiten horas futuras del día
actual. El catálogo aplica límites inclusivos: temperaturas de −15 a 50 °C, lluvia diaria de
0 a 300 mm y horaria de 0 a 100 mm.

Con éxito devuelve **201**:

```json
{
  "correccion": {
    "id": 1,
    "estacion": "cp-san-clemente-01",
    "fecha": "2025-01-16",
    "hora": null,
    "timestamp": "2025-01-16T12:00:00-03:00",
    "variable": "temperatura_media",
    "frecuencia": "D",
    "valor_anterior": null,
    "valor_nuevo": 21.0,
    "motivo": "Planilla manual del predio, registro del 16 de enero",
    "autor": "Nombre de quien revisó el dato",
    "creada_en": "2026-10-26T10:00:00-03:00",
    "estado": "vigente",
    "carga_origen": null,
    "fila_origen": null,
    "anterior": null,
    "revertida_en": null,
    "revertida_por": "",
    "motivo_reversion": ""
  },
  "actualizacion": {"ok": true}
}
```

La respuesta anterior es ilustrativa. Los identificadores, valores y fechas de creación
salen de la base. `valor_anterior` puede ser null; si un Excel tenía un valor no finito,
la bitácora lo representa como texto para conservar un JSON válido.

## Bitácora y reversión

`GET /api/v1/correcciones?estacion=<codigo>` devuelve la bitácora paginada:
`count`, `next`, `previous`, `results`. Sin filtro incluye todas las estaciones.
Ordena de la corrección más reciente a la más antigua.

`POST /api/v1/correcciones/<id>/revertir` recibe:

```json
{"autor": "Nombre del revisor", "motivo": "Se anuló la planilla manual"}
```

Devuelve **200** con la misma estructura `correccion` y `actualizacion`. Restaura el valor,
el origen, la carga y las marcas de calidad anteriores. Si la medición no existía, la elimina;
no crea un null artificial. Recalcula también los resúmenes e índices para que no quede un
valor antiguo publicado.

Otra corrección sobre la misma estación, instante, variable y frecuencia deja la anterior
como `reemplazada`. Solo se puede revertir la vigente. Al revertirla se recupera la anterior
y su estado `vigente`; se puede continuar deshaciendo en ese orden. La reversión registra
también autor, motivo y fecha. No borra la bitácora.

## Recálculo y errores

Cada creación y reversión guarda primero el cambio y su auditoría en una transacción.
Luego ejecuta `actualizar_todo --sin-satelite` y espera su resultado. Usa el mismo candado
de PostgreSQL que E1C-129, para serializar correcciones y actualizaciones programadas.
Tras una respuesta exitosa, `GET /api/v1/datos` contiene el resultado recalculado.

| HTTP | Significado |
| --- | --- |
| 400 | Campos inválidos, rango físico, fecha, hora, frecuencia o carga de origen incorrectos. No guarda cambios. |
| 401 | Falta la clave, es incorrecta o no está configurada. |
| 404 | No existe el identificador solicitado para revertir. |
| 409 | La corrección ya no está vigente o la medición fue modificada por otro proceso. No sobrescribe ese cambio. |
| 503 | La corrección o reversión se guardó, pero falló el recálculo. La respuesta incluye su ID y `actualizacion.ok: false`. |

Ante 503, no repetir el POST: revisar los logs y ejecutar
`python manage.py actualizar_todo --sin-satelite` en el servicio correspondiente. La bitácora
permite identificar el cambio pendiente de publicación. No se afirma que el JSON esté
actualizado si el comando falla.

## Integración con las otras tareas

- **E1C-70:** conserva la falla original con `corregido: true` y los IDs de las correcciones
  vigentes. Los rechazos se vinculan por carga y número de fila; no se marca toda la carga.
  El CSV conserva sus columnas y muestra `Sí`/`No`. El resumen cuenta también estas fallas
  históricas corregidas; no equivale al número de problemas pendientes.
- **E1C-132:** `MedicionHoraria.origen` es `excel` o `manual`; las filas anteriores migran
  a `excel`. `CorreccionManual.timestamp`, `variable`, `frecuencia` y `estado="vigente"`
  identifican la corrección activa. `ResumenDiario.origen` mantiene su significado D/H.
  Las recargas conservan el manual ante un vacío o valor imposible. Un valor válido de
  un Excel aplicable lo reemplaza y registra la carga en `reemplazada_por`. La API no
  reprocesa el mismo archivo (hash). La reversión de una corrección reemplazada responde
  409. Los días y fichas publican la marca y el conteo de correcciones vigentes según el
  [contrato de datos](contrato/CONTRATO_DATOS.md#correcciones-y-recargas--e1c-132).
- **E1C-68 / E1C-66:** `apps/ingesta/autenticacion.py` y `INGESTA_API_KEY` son compartidos.
  El catálogo público conserva sus lecturas sin clave; las correcciones usan la subclase
  privada, que exige clave también al leer autores y motivos.

La migración `0015_correcciones_manuales` conserva los datos existentes. Hay una restricción
única condicional para impedir más de una corrección vigente por medición. Los tests usan
archivos temporales y datos sintéticos; no modifican las salidas reales de `data/cliente`.
