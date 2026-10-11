# Datos sintéticos y test del JSON completo

Esta carpeta tiene un generador de datos climáticos **ficticios y siempre idénticos** (semilla
fija). Sirven para un solo propósito: que el test
`apps/clima/tests/test_json_completo.py` avise cuando un cambio altera los resultados.


## Archivos

| Archivo | Para qué |
|---|---|
| `generar_datos.py` | Genera los datos diarios de 2 estaciones ficticias. Solo usa la biblioteca estándar. |
| `comparar_json.py` | Compara dos JSON de `exportar_json` e imprime qué campos cambiaron. Lo usa el test y también se corre a mano. |
| `../../apps/clima/tests/test_json_completo.py` | El test de punta a punta. |
| `../../apps/clima/tests/referencia/json_completo.json` | El JSON de referencia que el test compara. Se sube a Git. |

## Qué datos genera

Datos diarios (`frecuencia="D"`, a las 12:00 de Chile, como los deja `ingestar_excel`), sin fechas
futuras: terminan en junio de 2025, así que todas las temporadas están cerradas.

| Estación | Código | Período | Qué tiene de particular |
|---|---|---|---|
| Sintética Norte | `sint-norte-01` | 2021-07-01 a 2025-06-30 (4 temporadas) | Latitud -35,52. Días sin dato al azar (2 %). Rachas sobre 35 °C: 7 días (2022), 3 (2023, sin incidencia), 6 y 5 cortadas por un día sin dato (2024) y 6 (2025). |
| Sintética Sur | `sint-sur-01` | 2022-05-01 a 2025-06-30 | **Sin latitud** (el Huglin nunca es confiable). Hueco de 55 días en el verano 2023-2024 (Winkler no confiable, 74,5 %). La temporada 2021-2022 solo tiene mayo-junio (sin índices ni clasificación). 20 días de junio de 2024 sin precipitación. |

Los casos borde están escritos a mano en `ESTACIONES` (no dependen de la suerte de la semilla). Lo
demás (temperaturas, lluvia) sale de una curva estacional con ruido y un valor distinto por
temporada y por año, para que haya temporadas frías, cálidas, secas y lluviosas.

Para mirar los datos como CSV (el test no lo usa, **no lo subas a Git**):

```powershell
python data/synthetic/generar_datos.py --salida data/synthetic/datos_sinteticos.csv
```

## Cómo funciona el test

1. Borra las estaciones que dejan las migraciones y crea las 2 sintéticas (así la referencia no
   depende de los datos reales de las migraciones).
2. Carga los datos sintéticos directo en `MedicionHoraria`. **No pasa por `ingestar_excel`.**
3. Corre `generar_resumenes` → `calcular_indices` → `exportar_json`.
4. Quita `generado` y `temporada_en_curso` (cambian en cada exportación) y compara todo el resto
   con `referencia/json_completo.json`. Si algo cambió, el fallo lista los campos, por ejemplo:
   `$.ficha_temporada[3: estacion_id=sint-norte-01, temporada=2024-2025].indices.winkler.valor: antes 2006.4, ahora 2010.1`.

Además hay tests de `calcular_indices` que calculan Winkler, Huglin y días sobre 35 °C
**directo desde los datos crudos** (sin usar el código del repo) y comparan con lo que quedó en la
base: no dependen de la referencia.

Correrlos:

```powershell
docker compose exec backend pytest apps/clima/tests/test_json_completo.py
```

## Regenerar la referencia cuando un cambio es intencional

Solo se regenera cuando **el resultado debe cambiar** (por ejemplo, el PO decide si una temporada
terminada entra o no en su propio promedio, se confirman los cortes con el enólogo, o se corrige
una fórmula). Nunca para "hacer pasar" un test que no entiendes.

1. Regenera (esto sobrescribe el archivo y el test queda como *skipped*, es lo esperado):

   ```powershell
   docker compose exec -e REGENERAR_REFERENCIA=1 backend pytest apps/clima/tests/test_json_completo.py::test_json_completo_coincide_con_la_referencia
   ```

   Si después no ves el archivo cambiado en tu carpeta (tu `docker compose` no monta el repo),
   cópialo desde el contenedor con `docker compose cp` hacia
   `apps/clima/tests/referencia/json_completo.json`.

2. **Revisa el diff**: `git diff apps/clima/tests/referencia/json_completo.json`. Cada línea que
   cambió tiene que poder explicarse con tu cambio. Si cambió algo que no esperabas, es una
   regresión: no la subas.
3. Corre el test de nuevo, sin la variable, y confirma que pasa:

   ```powershell
   docker compose exec backend pytest apps/clima/tests/test_json_completo.py
   ```

4. Sube la referencia **en el mismo PR** que el cambio, y explica en "Contexto para el equipo"
   qué campos cambiaron y por qué.

También hay que regenerarla si se toca `generar_datos.py` (cualquier número, incluida `SEMILLA`).
Los casos borde de la referencia están protegidos por `test_la_referencia_incluye_los_casos_borde`:
si un cambio al generador los deja fuera, ese test falla.

La primera vez (cuando el archivo aún no existe) el test falla pidiendo crearla: se hace con el
mismo comando del paso 1.

## Comparar el JSON real antes de mergear un PR

El test usa datos ficticios; los datos reales (los de `data/cliente`, que no se sube) pueden
revelar cosas que los sintéticos no. Antes de mergear un PR, quien lo hizo compara el JSON real
en su máquina:

```powershell
# 1. Con tu rama actualizada pero SIN tu cambio (por ejemplo, en refactor):
docker compose exec backend python manage.py exportar_json --salida data/cliente/antes.json --sobrescribir

# 2. Con tu cambio:
docker compose exec backend python manage.py exportar_json --salida data/cliente/despues.json --sobrescribir

# 3. Comparar (con el Python de Windows, no necesita Docker):
python data/synthetic/comparar_json.py data/cliente/antes.json data/cliente/despues.json
```

Termina con código 0 si no hay diferencias y 1 si las hay (lista hasta 50; usa `--maximo` para ver
más). Dos precauciones: hazlo con la **misma base de datos** (si cargaste datos entre medio, la
diferencia no es de tu código) y el **mismo día** (la temporada en curso cambia a diario). Las
diferencias tienen que ser exactamente las que tu PR dice que produce.

## Lo que este test NO cubre

- **`ingestar_excel`**: los datos se cargan directo en `MedicionHoraria`. La ingesta tiene sus
  propios tests; las tareas de ingesta tendrán que agregar los suyos.
- **Datos horarios** (`eventos_lluvia`): no hay datos horarios en el sintético, igual que en los
  reales hoy. Cuando lleguen, hay que agregar una estación horaria al generador.
- **Temporada en curso** (comparación "al mismo día"): todas las temporadas sintéticas están
  cerradas, para que el resultado no dependa de la fecha en que corre el test. Las tareas de
  fechas tendrán que agregar un caso con la fecha fijada.
- **Los umbrales de `settings`**: el test fija `UMBRAL_CALOR_C = 35` y
  `MINIMO_DIAS_INCIDENCIA = 5` para no depender del `.env` de cada máquina. Un cambio en esos
  valores por defecto no hace fallar el test.
