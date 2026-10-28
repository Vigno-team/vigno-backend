# VIGNO Backend

Sistema de apoyo a la decisión de fecha de cosecha para **Casas Patronales**.

Backend en Django + Django REST Framework sobre PostgreSQL 16. Recibe los Excel de las
estaciones meteorológicas, calcula los resúmenes diarios y los índices de cada temporada,
y entrega todo al frontend por una API y un JSON consolidado. El frontend vive en el
repositorio [`vigno-fronted`](https://github.com/Vigno-team/vigno-fronted) (rama `develop`).

---

## Cómo fluyen los datos

```
Excel de una estación
  (data/raw + ingestar_excel, o POST /api/v1/cargas)
        │
        ▼
MedicionHoraria ──► generar_resumenes ──► ResumenDiario ──► calcular_indices (Winkler, Huglin)
                                                                  │
                                                                  ▼
                                    exportar_json ──► DATOS_DIR/vigno-datos-reales.json
                                                                  │
                                                                  ▼
                                                     GET /api/v1/datos (frontend)
```

`actualizar_todo` corre todos los pasos de cálculo en orden. Lo usan la carga por API, las
correcciones manuales y el servicio `tareas` del despliegue, así que normalmente no hace falta
correr los pasos uno por uno.

---

## Requisitos

Hay dos formas de trabajar. Elige una:

- **Con Docker** (recomendada): Docker, Docker Compose y Git.
- **Sin Docker** (Windows): Python 3.11, PostgreSQL 16 y Git. Ver
  [Levantar sin Docker en Windows](#levantar-sin-docker-en-windows).

---

## Levantar el proyecto (con Docker)

```bash
git clone https://github.com/Vigno-team/vigno-backend.git
cd vigno-backend

cp .env.example .env      # completar valores si hace falta
docker compose up --build
```

El contenedor aplica las migraciones al partir. Cuando termine, verifica que todo esté bien:

| URL                               | Qué es                                    |
| --------------------------------- | ----------------------------------------- |
| http://localhost:8000/api/health/ | Estado de la API y de la base de datos    |
| http://localhost:8000/api/docs/   | Documentación interactiva de la API       |
| http://localhost:8000/api/schema/ | Contrato OpenAPI (lo consume el frontend) |
| http://localhost:8000/admin/      | Admin de Django                           |

Si `/api/health/` devuelve `"status": "ok"`, tu entorno está listo. La base parte vacía: para
ver datos hay que [cargar los Excel del cliente](#cargar-los-datos-del-cliente).

Para crear un usuario del admin:

```bash
docker compose exec backend python manage.py createsuperuser
```

Para probar las rutas que escriben datos (cargas, alta de estaciones y correcciones), pon un
valor en `INGESTA_API_KEY` dentro de tu `.env`. Si queda vacía, esas rutas responden 401.

---

## Cargar los datos del cliente

Los Excel de Casas Patronales (San Clemente 2020 a 2026 y El Arenal 2021 a 2026) se comparten
por el Drive del equipo. Nunca entran al repositorio.

1. Copia los Excel a `data/raw/` (ignorada por Git). En Docker, la carpeta del proyecto está
   montada en `/app`, así que el contenedor los ve.

2. Cárgalos. Uno por uno:

   ```bash
   docker compose exec backend python manage.py ingestar_excel --archivo "data/raw/San Clemente 2024.xlsx" --estacion "San Clemente"
   ```

   O todos de una vez, desde Git Bash:

   ```bash
   for f in data/raw/*.xlsx; do n=$(basename "$f" .xlsx); docker compose exec -T backend python manage.py ingestar_excel --archivo "$f" --estacion "${n% *}"; done
   ```

   O desde PowerShell:

   ```powershell
   Get-ChildItem data/raw/*.xlsx | ForEach-Object { docker compose exec -T backend python manage.py ingestar_excel --archivo "data/raw/$($_.Name)" --estacion ($_.BaseName -replace ' \d{4}$', '') }
   ```

   `--estacion` es el nombre de la estación (`San Clemente`, `El Arenal`). La temporada se
   detecta del título o del nombre del archivo; si no se puede, se indica con `--temporada 2024`.
   La carga es idempotente: repetirla no duplica datos.

3. Calcula todo y genera el JSON del frontend:

   ```bash
   docker compose exec backend python manage.py actualizar_todo --sin-satelite
   ```

4. Comprueba: `http://localhost:8000/api/v1/temporadas` debe devolver las temporadas
   (`["2019-2020", ..., "2026-2027"]`) y `http://localhost:8000/api/v1/datos` el JSON completo.

También se puede cargar un Excel por la API, con validación previa. Ver
[Carga de Excel por API](#carga-de-excel-por-api-e1c-66).

### Conectar el frontend en desarrollo

El frontend corre con Vite en `localhost:5173` y no tiene proxy hacia el backend, así que debe
llamar al puerto 8000: `VITE_API_BASE_URL=http://localhost:8000/api` en su `.env`, y en el
código `${import.meta.env.VITE_API_BASE_URL}/v1/...`. El CORS ya permite `localhost:5173`
(`CORS_ALLOWED_ORIGINS`). Una llamada a `localhost:5173/api/...` nunca llega a Django.

En el despliegue el frontend se construye con `VITE_API_BASE_URL=/api` y nginx redirige `/api/`
al backend, así que el mismo código funciona sin cambios.

---

## Levantar sin Docker en Windows

Todos los comandos son de PowerShell.

1. **Instalar** [Python 3.11](https://www.python.org/downloads/) (marca "Add python.exe
   to PATH"), [PostgreSQL 16](https://www.postgresql.org/download/windows/) y Git.
   PostgreSQL normal, sin extensiones adicionales.

2. **Crear la base** desde "SQL Shell (psql)" con el usuario `postgres`:

```sql
   CREATE USER vigno_user WITH PASSWORD 'vigno_password' CREATEDB;
   CREATE DATABASE vigno_db OWNER vigno_user;
```
   `CREATEDB` hace falta porque pytest crea una base temporal para los tests.

3. **Clonar e instalar dependencias:**

```powershell
   git clone https://github.com/Vigno-team/vigno-backend.git
   cd vigno-backend
   python -m venv .venv
   Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
   .venv\Scripts\Activate.ps1
   pip install -r requirements-dev.txt
```
   `Set-ExecutionPolicy` es solo para esa ventana y no pide permisos de administrador: sin él,
   Windows bloquea `Activate.ps1`. Repítelo cada vez que abras una ventana nueva.

4. **Configurar `.env`:**

```powershell
   Copy-Item .env.example .env
```
   Edita `.env` y cambia `POSTGRES_HOST=db` por `POSTGRES_HOST=localhost`. Los demás
   valores deben coincidir con los del paso 2.

5. **Migrar y levantar:**

```powershell
   python manage.py migrate
   python manage.py runserver
```
   Verifica en http://localhost:8000/api/health/.

6. **Cargar los datos** (con los Excel en `data/raw/`):

```powershell
   python manage.py ingestar_excel --archivo "data/raw/San Clemente 2024.xlsx" --estacion "San Clemente"
   python manage.py actualizar_todo --sin-satelite
```
   `ingestar_excel` va una vez por cada Excel; `actualizar_todo` se corre al final.

7. **Tests y linter:**

```powershell
   pytest
   ruff check .
   ruff format --check .
```

Si el puerto 5432 está ocupado, apaga el contenedor de Docker (`docker compose down`)
o cambia `POSTGRES_PORT` en `.env`.

---

## Comandos frecuentes

```bash
docker compose up                                  # levantar
docker compose down                                # apagar
docker compose down -v                             # apagar y borrar la base
docker compose logs -f backend                     # ver logs

docker compose exec backend python manage.py makemigrations
docker compose exec backend python manage.py migrate
docker compose exec backend pytest                 # correr tests
docker compose exec backend ruff check .           # linter
docker compose exec backend ruff format --check .  # formato
```

### Comandos de `manage.py`

| Comando | Qué hace |
| --- | --- |
| `ingestar_excel --archivo <ruta> --estacion <nombre> [--temporada <año>]` | Carga un Excel de estación en `MedicionHoraria` usando `config/mapeos_estaciones.json` |
| `generar_resumenes [--estacion <nombre>]` | Pasa las mediciones a resúmenes diarios (`ResumenDiario`) |
| `calcular_indices [--estacion <nombre>]` | Calcula Winkler y Huglin por temporada |
| `validar_rangos [--estacion <nombre>]` | Vuelve a marcar el histórico con `config/rangos_variables.json`, sin tocar los valores |
| `actualizar_todo [--sin-satelite \| --forzar-satelite]` | Corre todos los pasos de cálculo y deja el JSON del frontend ([detalle](#actualizar-todo-e1c-129)) |
| `exportar_json [--salida <ruta>] [--sobrescribir]` | Escribe `DATOS_DIR/vigno-datos-reales.json` |
| `cargar_areas_mapa [--solo-validar]` | Valida `config/areas_mapa.json` y copia la ubicación de cada estación a la base |
| `actualizar_mapa_calor --estacion <código> --capa ndvi` | Pide a Copernicus la capa NDVI de un predio |
| `cargar_dataset_ficticio` | Une los Excel del dataset de California en `data/ficticio/cosechas.csv` |
| `clasificar_temporadas` | Calidad de cada temporada del dataset ficticio |
| `correlacionar_madurez` | Correlaciona índices climáticos con fecha de cosecha y madurez (dataset ficticio) |
| `entrenar_cosecha [--anios-prueba <años>]` | Entrena y evalúa el modelo de ventana de cosecha (requiere `requirements-ml.txt`) |
| `exportar_prediccion_ficticia` | Escribe `data/ficticio/prediccion_ficticia.json` con lo que dejó `entrenar_cosecha` |

`--estacion` recibe el nombre de la estación en todos los comandos, salvo
`actualizar_mapa_calor`, que recibe el código (por ejemplo `cp-san-clemente-01`).

---

## Variables de entorno

Se leen del `.env` (ver `.env.example`). El despliegue usa su propio `deploy/.env`.

| Variable | Para qué |
| --- | --- |
| `SECRET_KEY`, `DEBUG`, `DJANGO_SETTINGS_MODULE`, `ALLOWED_HOSTS` | Configuración de Django |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT` | Conexión a PostgreSQL (`POSTGRES_HOST=db` con Docker, `localhost` sin Docker) |
| `CORS_ALLOWED_ORIGINS` | Orígenes del frontend que pueden llamar a la API |
| `INGESTA_API_KEY` | Clave de la cabecera `X-Api-Key` para cargas, estaciones y correcciones. Vacía, nadie puede escribir |
| `DATOS_DIR` | Carpeta donde quedan el JSON del frontend, `actualizacion.json` y los Excel subidos (por defecto `data/cliente`) |
| `CDSE_CLIENT_ID`, `CDSE_CLIENT_SECRET` | Credenciales de Copernicus Data Space para el mapa de calor. Sin ellas, ese paso se omite |

Opcionales, con valor por defecto en `vigno/settings/base.py`: `UMBRAL_CALOR_C` (35),
`MINIMO_DIAS_INCIDENCIA` (5), `UMBRAL_LLUVIA_INTENSA_MM` (10) y `FACTOR_MES_INUSUAL` (2).

---

## Estructura

```
vigno/                  configuración del proyecto Django
  settings/             base.py, development.py, production.py
apps/
  clima/                mediciones, resúmenes, índices, resultados, fallas, correcciones,
                        mapa de calor, API de resultados y health check
    prediccion/         modelo de ventana de cosecha y análisis del dataset de California
  ingesta/              carga de Excel (carga.py), API de cargas, bitácora RegistroCarga
                        y la clave X-Api-Key (autenticacion.py)
config/                 mapeos de estaciones, rangos físicos, umbrales de validación y áreas del mapa
deploy/                 despliegue completo: compose, nginx, frontend y servicio de tareas
docs/                   guías por tema y contrato de datos con el frontend
data/synthetic/         generador de datos falsos y test del JSON completo
notebooks/              exploración y spikes de ciencia de datos
tests/                  tests transversales (health check y despliegue)
```

Dependencias: `requirements.txt` (API), `requirements-dev.txt` (tests y linter) y
`requirements-ml.txt` (scikit-learn y notebooks). El compose de desarrollo instala las dos
primeras; las de ML se instalan aparte cuando hacen falta.

---

## API

El esquema OpenAPI se genera solo desde el código y se publica en `/api/schema/`, con
documentación navegable en `/api/docs/`. El contrato de datos con el frontend está en
[docs/contrato/CONTRATO_DATOS.md](docs/contrato/CONTRATO_DATOS.md). Cualquier cambio que
modifique la forma de una respuesta necesita aviso al PO del otro equipo antes de mergearse.

| Ruta | Método | Clave | Qué devuelve |
| --- | --- | --- | --- |
| `/api/health/` | GET | No | Estado de la API y de la base |
| `/api/v1/datos` | GET | No | JSON completo para el frontend (503 si aún no se generó) |
| `/api/v1/estaciones` | GET | No | Estaciones y calidad de sus datos |
| `/api/v1/estaciones` | POST | Sí | Da de alta una localidad nueva |
| `/api/v1/temporadas` | GET | No | Temporadas con datos, de la más antigua a la más reciente |
| `/api/v1/temporadas/{temporada}?estacion={codigo}` | GET | No | Ficha de una estación y temporada |
| `/api/v1/rachas/{temporada}?estacion={codigo}` | GET | No | Rachas de calor de la temporada |
| `/api/v1/calidad/fallas?estacion={codigo}&temporada={temporada}` | GET | No | Reporte de datos con falla (`&formato=csv` para CSV) |
| `/api/v1/cargas` | POST | Sí | Sube un Excel, lo valida, lo guarda y recalcula |
| `/api/v1/cargas`, `/api/v1/cargas/{id}` | GET | Sí | Historial y detalle de las cargas |
| `/api/v1/correcciones` | GET, POST | Sí | Bitácora de correcciones y nueva corrección manual |
| `/api/v1/correcciones/{id}/revertir` | POST | Sí | Revierte una corrección |

`{temporada}` va como `2024-2025` y `{codigo}` es el `id` que devuelve `/api/v1/estaciones`
(por ejemplo `cp-san-clemente-01`). Las rutas de lectura sin clave son públicas, según el
contrato de la demo.

Pendientes de E1C-93: `GET /api/v1/actualizacion` (para que el frontend sepa cuándo hay datos
nuevos) y `GET /api/v1/prediccion-ficticia`. Todavía no existen.

### La clave `X-Api-Key`

Las rutas marcadas con clave piden la cabecera `X-Api-Key` con el valor de `INGESTA_API_KEY`.
Sin ella, o con otra, responden 401. Es una sola clave para todo el backend y es provisoria
hasta el login de E1C-64.

- La genera quien levanta el servidor:
  `python -c "import secrets; print(secrets.token_urlsafe(32))"`.
- Va solo en `deploy/.env` (en local, en `.env`). Nunca en el repo, Jira, Drive ni chats.
  Sin ella, `docker compose -f deploy/docker-compose.yml` no arranca.
- Al usuario que sube los Excel se le entrega en persona, como una contraseña. La escribe
  en la pantalla de carga; el frontend la guarda solo durante la sesión y la manda en
  `X-Api-Key`. Nunca va en el código del frontend ni en variables `VITE_`.
- Si se filtra, se cambia en `deploy/.env` y se reinicia el backend.

En el código: `ApiKeyAuthentication` (`apps/ingesta/autenticacion.py`) pide la clave solo para
escribir; `ApiKeyPrivadaAuthentication` la pide también para leer (cargas y correcciones).

### Resultados por temporada (E1C-17)

La ficha usa índices reales guardados, metadatos de calidad y nulos explícitos, e incluye la
clasificación térmica e hídrica de la temporada (E1C-18). No ejecuta la ingesta ni recalcula
índices: lee lo que dejaron `generar_resumenes` y `calcular_indices`. Ver
[la guía de E1C-17](docs/E1C-17_RESULTADOS.md) para probar los endpoints y las reglas de calidad.

### JSON para el frontend

`GET /api/v1/datos` sirve `DATOS_DIR/vigno-datos-reales.json`, que deja `actualizar_todo`
(paso `exportar_json`). Tiene los mismos bloques que los endpoints de resultados. Si el archivo
aún no existe o no es válido, responde 503 con `Retry-After`; no sirve datos de ejemplo. La
respuesta no se cachea (`Cache-Control: no-store`).

El archivo tiene datos del cliente: no se sube al repo. Se puede generar a mano con
`python manage.py exportar_json --sobrescribir`.

### Localidades nuevas (E1C-68)

`POST /api/v1/estaciones` (con clave) da de alta una estación con `nombre`, `latitud` y
`longitud` obligatorios, y `subzona` y `propietario` opcionales:

- `201`: la estación creada, con su `id` (código) propio.
- `409`: ya existe una con ese nombre, sin distinguir mayúsculas ni tildes. Devuelve la
  existente para que el frontend la ofrezca.
- `400`: faltan datos o las coordenadas no caen dentro de Chile.

Una estación sin mapeo propio en `config/mapeos_estaciones.json` carga sus Excel con la
plantilla `formato_estandar` (la misma de San Clemente y El Arenal). Si la estación no existe,
la carga responde "La estación X no existe; créala primero". Apenas tiene datos,
`actualizar_todo` la incluye en `/api/v1/datos`.

### Carga de Excel por API (E1C-66)

Un Excel de estación se sube desde la plataforma, se valida antes de guardar y el sistema
se recalcula solo. Usa la misma lógica que `ingestar_excel` (`apps/ingesta/carga.py`) y
los mapeos de `config/mapeos_estaciones.json`.

| Endpoint                             | Qué hace                                                |
| ------------------------------------ | ------------------------------------------------------- |
| `POST /api/v1/cargas`                | Valida, guarda y corre `actualizar_todo --sin-satelite` |
| `POST /api/v1/cargas?solo_validar=1` | Vista previa: lo que pasaría, sin guardar nada          |
| `GET /api/v1/cargas`                 | Las últimas 20 cargas                                   |
| `GET /api/v1/cargas/<id>`            | Estado, filas y rechazos con su motivo                  |

Las cuatro piden la clave.

```bash
curl -H "X-Api-Key: $INGESTA_API_KEY" \
  -F "archivo=@San Clemente 2024.xlsx" -F "estacion=cp-san-clemente-01" \
  http://localhost:8000/api/v1/cargas
```

`estacion` acepta el código (el `id` de `/api/v1/estaciones`) o el nombre. `temporada`
(año) es opcional: si no viene, se detecta del título o del nombre del archivo.

**Respuestas:**

- `201`: carga nueva. Trae el `id`, la estación, la temporada, `fecha_desde`/`fecha_hasta`,
  los `conteos` (insertados, actualizados, sin cambio, omitidos y rechazados), los
  `rechazos` con su motivo, las `celdas_vacias_conservadas` y el `recalculo` (lo que dejó
  `actualizacion.json`).
- `200` con `"repetida": true`: ese mismo archivo (mismo SHA-256) ya se cargó bien en esa
  estación; no se procesa de nuevo ni se recalcula.
- `400`: falta el archivo o la estación, la estación no existe, la extensión no es
  `.xls`/`.xlsx` o pesa más de 20 MB.
- `401`: falta la clave o no es la correcta.
- `422`: el archivo no sirve y no se guardó nada. Pasa si está dañado o protegido, si no
  tiene la hoja `mensual`, si los encabezados no calzan con ningún formato (indica las
  columnas que faltan respecto del más parecido), si más del 20 % de las fechas son
  inválidas, si temperatura máxima, mínima o media vienen vacías o no numéricas en más
  del 50 % de las filas, o si no queda ninguna fila válida.

Los errores vienen como `{"valido": false, "errores": ["..."]}`, con motivos legibles. Los
umbrales están en `config/validacion_cargas.json` para ajustarlos sin tocar código. Lo que
no alcanza para rechazar el archivo se acepta, y las filas malas quedan en el reporte de
fallas (E1C-70). Estas reglas de umbral solo las aplica la API; `ingestar_excel` mantiene
su comportamiento.

**Una celda vacía no borra un dato ya cargado.** Si un día ya tiene valor y la recarga
trae esa celda vacía o con texto, se conserva el valor y se cuenta como "sin cambio". No
es una falla (el dato sigue en la base), así que no aparece en `/api/v1/calidad/fallas`:
queda en `RegistroCarga.celdas_vacias_conservadas` (fila, fecha y variable) y se muestra en
la respuesta del POST, en `solo_validar` y en `GET /api/v1/cargas/<id>` con el aviso
"Celda vacía: se conservó el valor anterior". Si no había un valor antes, queda como nulo
y aparece en el reporte de fallas como siempre. Aplica a la API y a `ingestar_excel`.

El archivo subido queda en `DATOS_DIR/cargas/<hash>.<ext>` (dentro de `data/cliente/`,
ignorado por Git). La carga usa el mismo candado que `actualizar_todo`: si el programador
está recalculando, la carga espera.

### Correcciones manuales (E1C-131)

`POST /api/v1/correcciones` guarda un valor con autor y motivo y recalcula con
`actualizar_todo --sin-satelite`. La bitácora se consulta con GET en la misma ruta;
`POST /api/v1/correcciones/<id>/revertir` recupera el dato anterior y recalcula. Las tres
rutas piden la clave.

El valor corregido queda en `MedicionHoraria` con `origen="manual"`; lo que viene de un Excel
tiene `origen="excel"`. El reporte de fallas conserva el problema original y lo marca con
`corregido: true` mientras la corrección esté vigente. Si falla el recálculo, la API responde
503 con el ID guardado para evitar repetir el cambio. El contrato, los ejemplos y la
coordinación con la recarga de Excel están en
[docs/E1C-131_CORRECCIONES.md](docs/E1C-131_CORRECCIONES.md).

---

## Actualizar todo (E1C-129)

Un solo comando recalcula todo y deja listos los datos del frontend. Lo usan la carga de
Excel por API, las correcciones manuales y el servicio `tareas` del despliegue:

```bash
docker compose exec backend python manage.py actualizar_todo
```

Corre estos pasos en orden, para todas las estaciones:

| Paso                           | Qué hace                                                                   | Crítico |
| ------------------------------ | -------------------------------------------------------------------------- | ------- |
| `generar_resumenes`            | Pasa las mediciones horarias a resúmenes diarios                           | Sí      |
| `calcular_indices`             | Calcula Winkler y Huglin por temporada                                     | Sí      |
| `clasificar_temporadas`        | Calidad del histórico de California. Se omite si falta `data/ficticio/cosechas.csv` | Sí, si hay CSV |
| `actualizar_mapa_calor`        | Capa NDVI de Sentinel-2 por estación con contorno en `config/areas_mapa.json` | No   |
| `entrenar_cosecha`             | Reentrena si existen `cosechas.csv` y scikit-learn, y el CSV es más nuevo que la evaluación | No |
| `exportar_prediccion_ficticia` | Regenera `data/ficticio/prediccion_ficticia.json` si existe la evaluación  | No      |
| `exportar_json`                | Escribe `DATOS_DIR/vigno-datos-reales.json`                                | Sí      |

El mapa de calor solo se pide si están `CDSE_CLIENT_ID` y `CDSE_CLIENT_SECRET` en `.env`
y la última imagen guardada tiene más de 5 días (Sentinel-2 pasa cada ~5 días). Opciones:

- `--sin-satelite`: no consulta Copernicus.
- `--forzar-satelite`: consulta aunque la imagen tenga menos de 5 días.

**Si un paso falla**, se registra y se siguen corriendo los demás, para que una caída de
Copernicus no deje al frontend sin datos. El comando termina con error solo si falla un
paso crítico. Los pasos que no corresponden quedan como omitidos, sin error.

Si se lanzan dos a la vez (la carga por API y el programador), el segundo espera a que
termine el primero (`pg_advisory_lock`). Los JSON se escriben de forma atómica: la API
lee el archivo anterior o el nuevo, nunca uno a medias.

**Dónde quedan los archivos:** en la carpeta `DATOS_DIR` del `.env` (por defecto
`data/cliente`; acepta una ruta relativa a la raíz del proyecto o absoluta):

- `vigno-datos-reales.json`: los datos para el frontend, que sirve `GET /api/v1/datos`.
- `actualizacion.json`: el resultado de la última corrida. Lo va a leer
  `GET /api/v1/actualizacion` (E1C-93) para que el frontend sepa que hay datos nuevos.
  El formato está acordado con E1C-93: no cambiarlo sin avisar.

```json
{
  "generado": "2026-10-22T14:03:11-03:00",
  "ok": true,
  "pasos": [
    {"paso": "generar_resumenes", "ok": true, "segundos": 0.22, "detalle": ""},
    {"paso": "actualizar_mapa_calor", "ok": false, "segundos": 60.1,
     "detalle": "con error: cp-san-clemente-01: Error al solicitar el GeoTIFF..."},
    {"paso": "entrenar_cosecha", "ok": true, "segundos": 0.0,
     "detalle": "omitido: no existe data/ficticio/cosechas.csv"}
  ]
}
```

`ok` general es `false` solo si falló un paso crítico. Cada paso trae su propio `ok`, y
los omitidos tienen `ok: true` con un `detalle` que empieza con `omitido:`.

---

## Calidad del dato

### Rangos físicos (E1C-71)

`config/rangos_variables.json` es el catálogo único: temperaturas máxima,
mínima y media entre −15 y 50 °C; precipitación diaria entre 0 y 300 mm y
horaria entre 0 y 100 mm. Los límites están incluidos. El validador
`apps.clima.rangos.motivo_fuera_de_rango` acepta nombres canónicos y
`tmax/tmin/tmedia`, y lo usan también las correcciones manuales.

La ingesta conserva el número original en `MedicionHoraria.valor`, con
`fuera_de_rango=True` y `motivo_fuera_de_rango`. No lo sustituye por cero,
no lo imputa y no confunde esta marca con `motivo_nulo`. Una recarga válida
actualiza ambas marcas; se conserva la prevalencia del archivo más nuevo.

Los resúmenes excluyen las mediciones marcadas. La variable afectada del
día queda nula, con `motivo_nulo="Valor fuera de rango físico"`. Solo las
temperaturas marcadas cambian la confiabilidad térmica del día; una lluvia
marcada conserva la confiabilidad que resulte de las temperaturas y su
cobertura horaria. Las variables independientes válidas se conservan. Una
temperatura media horaria marcada invalida el resumen térmico de ese día,
aunque haya otras horas válidas. La lluvia marcada tampoco participa en
los eventos horarios. Al recalcular, los índices derivados que ya no tienen
datos se retiran para no conservar resultados obsoletos; las mediciones
originales permanecen guardadas.

Después de modificar el catálogo, para revalidar el histórico:

```powershell
docker compose exec backend python manage.py validar_rangos
docker compose exec backend python manage.py actualizar_todo --sin-satelite
```

`validar_rangos` es idempotente, actualiza solo marcas y motivos y admite
`--estacion "San Clemente"`. Las cargas nuevas se validan automáticamente.

### Reporte de fallas (E1C-70)

```text
GET /api/v1/calidad/fallas?estacion=<codigo>&temporada=2024-2025
GET /api/v1/calidad/fallas?estacion=<codigo>&temporada=2024-2025&formato=csv
```

El JSON devuelve `fallas`, un `resumen` por tipo y variable y los cuatro
`tipos_incluidos`: `rechazado`, `nulo`, `sin_registro` y `fuera_de_rango`.
Cada fila identifica estación, fecha local, variable, motivo, valor original
disponible, archivo y carga. Los rechazos incluyen el número de fila del Excel.
`corregido` pasa a `true` cuando la falla tiene una corrección manual vigente
(E1C-131); la falla original no desaparece. El CSV usa encabezados en español y
separador `;`. Consulta inválida responde 400 y estación inexistente 404. Es una
consulta de solo lectura y pública.

Los días sin registro se buscan entre el primer y el último día con algún valor de la
estación, dentro de la temporada solicitada y hasta hoy. Se devuelve una fila
por día, con variable nula (`sin_variable` en el resumen); no se crean mediciones.
Los valores ausentes siguen nulos: el pipeline no interpola, no rellena con
promedios ni convierte faltantes en cero. La prueba de integridad recorre
ingesta, resúmenes, índices, exportación y reporte con un Excel con huecos.

Un rechazo sin fecha válida conserva `fecha=null`. Se incluye si el año del
archivo coincide con alguno de los años de la temporada y se identifica con
`criterio_temporada=anio_archivo_fecha_desconocida`. Puede aparecer en las dos
temporadas que comparten ese año; no debe interpretarse como una fecha conocida.
Los rechazos con fecha se filtran por esa fecha, no por el año del archivo.
Si no hay fecha ni año de archivo, no es posible asignarlo a esta consulta.
En nulos históricos el valor original no está almacenado por separado:
`valor_original` queda null y `motivo` conserva la explicación de la ingesta.

La ingesta cuenta las filas sin fecha ni valores como `filas_vacias_ignoradas`
en `RegistroCarga`; conserva el número original de fila de los rechazos reales.
Una fecha vacía o inválida con datos sí se rechaza. El reporte toma únicamente
la última carga exitosa por estación y año de archivo (si no hay año, por nombre
de archivo). Una carga fallida no reemplaza el informe anterior. Las recargas
no acumulan rechazos viejos; la bitácora completa permanece guardada.

Se omiten del reporte los días futuros o posteriores al último dato. Para
las bitácoras antiguas se omite también el motivo exacto `Fecha inválida` con
valor `NaT`, identificado como relleno en los Excel del cliente. El motivo nuevo
`Fecha vacía o inválida en una fila con datos` siempre se conserva, incluso
si la fecha original está vacía. Se recomienda recargar los archivos antiguos
para reconstruir sus contadores. Las mediciones nulas anteriores al primer
valor de la estación no se muestran como fallas; no se borran de la base.

---

## Dataset ficticio de California

Mientras no haya un histórico de cosechas del cliente, el modelo se prueba con un dataset
público de California. Todo lo de esta sección usa datos ficticios para el proyecto y no
mezcla esos datos con los de las estaciones.

Fuente: Bai, Huiqing (2022), *data*, Figshare, CC BY 4.0.
https://doi.org/10.6084/m9.figshare.19807777.v1

### Cargar el histórico (E1C-78)

Descargar `data.zip` y colocar los originales `Subset1.xls`, `Subset2.xls` y
`Subset3.xls` en `data/ficticio/` (ignorado por Git). No renombrar .xls a .xlsx.
Después ejecutar:

```bash
docker compose exec backend python manage.py cargar_dataset_ficticio
```

Queda `data/ficticio/cosechas.csv`. El lector usa `data` en Subset1/2 y los índices anuales
de I:L de `Region_1` a `Region_5` en Subset3. Obtiene el año de la fecha de cosecha en
Subset1, convierte las regiones 1–5 a I–V y conserva las etiquetas originales de Recommend.
También acepta tablas .xlsx ya normalizadas, pero no dos versiones del mismo Subset a la vez.
No sustituye índices climáticos ausentes por cero.

### Clasificación de las temporadas (E1C-79)

`Recommend` de Subset1 describe la recomendación de los cultivares. Para el
indicador del proyecto se usa esta escala provisional, a confirmar con el enólogo:
`Particularly recommended` → alta, `Limited recommendation` → media y
`Not recommended` → baja. `Not fully tested` y `Table grape` quedan sin clasificación
y se excluyen del denominador de `pct_alta`, al igual que los datos faltantes. Sin
evaluaciones, el porcentaje queda nulo con motivo. No es una puntuación de cata de cada
vendimia. Las etiquetas desconocidas siguen produciendo un error para evitar clasificarlas
silenciosamente. Napa solo publica °Brix, sin inventar calidad.

```bash
docker compose exec backend python manage.py clasificar_temporadas
```

`actualizar_todo` también la corre cuando existe `cosechas.csv`.

### Ventana de cosecha (E1C-85)

`entrenar_cosecha` evalúa el modelo en años de California que no se usaron para entrenar, y
`exportar_prediccion_ficticia` deja el resultado en `data/ficticio/prediccion_ficticia.json`.
Necesita las dependencias de ML:

```bash
docker compose exec backend pip install -r requirements-ml.txt
docker compose exec backend python manage.py entrenar_cosecha --anios-prueba 1941
docker compose exec backend python manage.py exportar_prediccion_ficticia
```

El detalle de los datos, el modelo y la salida está en
[docs/E1C-85_PREDICCION.md](docs/E1C-85_PREDICCION.md).

---

## Despliegue completo (E1C-65)

Levanta base, backend, servicio de tareas y frontend detrás de nginx con un solo comando.

Requiere Git y Docker Desktop con contenedores Linux y Compose 2.17 o posterior.
El backend y el frontend deben quedar como carpetas hermanas:

```powershell
git clone https://github.com/Vigno-team/vigno-backend.git
git clone --branch develop https://github.com/Vigno-team/vigno-fronted.git
cd vigno-backend
Copy-Item deploy/.env.example deploy/.env
```

Editar `deploy/.env`: poner claves distintas para `SECRET_KEY`, `POSTGRES_PASSWORD` e
`INGESTA_API_KEY`. Sin `INGESTA_API_KEY` el despliegue no arranca. Para generar una clave
se puede usar `python -c "import secrets; print(secrets.token_urlsafe(48))"`.
Este archivo local está ignorado por Git y por la construcción de imágenes.
Las credenciales de Copernicus se agregan ahí; nunca en un commit.
Si los repositorios están en otra ubicación, ajustar `FRONTEND_DIR` (relativa
a `deploy/`, o absoluta). No reemplazar el `.env` usado para desarrollo.
Si falla la descarga de paquetes de Debian, `DEBIAN_MIRROR` permite elegir
otro [mirror oficial](https://www.debian.org/mirror/list), sin cambiar el Dockerfile.

Para comprobar la configuración sin levantar nada:

```powershell
docker compose -f deploy/docker-compose.yml config
```

Desde la raíz del backend:

```powershell
docker compose -f deploy/docker-compose.yml up --build
```

Para dejarlo en segundo plano y esperar los healthchecks:

```powershell
docker compose -f deploy/docker-compose.yml up --build -d --wait --wait-timeout 600
```

| Dirección | Contenido |
| --- | --- |
| http://localhost | Frontend de la rama develop |
| http://localhost/api/health/ | Estado de la API y conexión a PostgreSQL |
| http://localhost/api/v1/datos | JSON actualizado por el servicio tareas |
| http://localhost/api/docs/ | Documentación de la API |
| http://localhost/admin/ | Admin de Django, con sus estáticos |

`WEB_PORT` cambia el puerto publicado si el 80 está ocupado. Solo nginx publica
un puerto; PostgreSQL y Gunicorn se comunican dentro de la red del despliegue.
El Compose de la raíz sigue siendo exclusivamente de desarrollo.
Este despliegue utiliza otra base y otros volúmenes; los datos de desarrollo
no aparecen automáticamente.

El backend usa la etapa `production` del Dockerfile, sin pytest, Ruff ni Jupyter.
Al arrancar aplica migraciones, carga las coordenadas de `areas_mapa.json`, ejecuta
collectstatic y arranca Gunicorn con DEBUG=False. `ALLOWED_HOSTS` y
`CSRF_TRUSTED_ORIGINS` se leen de `deploy/.env`; conservar localhost y 127.0.0.1
para los healthchecks. La configuración entregada sirve HTTP en localhost.
Si se publica con HTTPS, configurar el dominio, los orígenes HTTPS y ambas
variables `SESSION_COOKIE_SECURE` y `CSRF_COOKIE_SECURE` en True.

El servicio `tareas` usa la misma base de imagen y añade `requirements-ml.txt`.
Ejecuta `actualizar_todo` al partir, espera a que termine y vuelve a ejecutarlo
cada `INTERVALO_ACTUALIZACION_MIN` (360 por defecto), contado desde el fin de
la corrida. Una falla se registra en el log, deja el servicio unhealthy y se
reintenta en el siguiente intervalo; no hay ejecuciones simultáneas del programador.
La falta de CSV ficticio o credenciales satelitales sigue las reglas de omisión
de E1C-129; no se inventan resultados.

Nginx envía `/api/` a Gunicorn. También envía `/data/climateData.json` a
`/api/v1/datos`, de modo que el frontend actual recibe datos de la API y no
el archivo de ejemplo incluido en su build. El frontend se construye con
`VITE_API_BASE_URL=/api`. El JSON no se cachea. Si aún no existe o no es válido,
la API responde 503 y Retry-After; no sirve datos ficticios como sustituto. El
servicio web espera la primera actualización correcta.

### Datos y operación

La base nueva empieza sin mediciones: la pantalla puede mostrar estaciones
sin datos hasta cargar los Excel. Hay dos formas de cargarlos:

- Desde la plataforma o con `POST /api/v1/cargas`, usando la `INGESTA_API_KEY` de
  `deploy/.env`. Valida el archivo y recalcula solo.
- Con los archivos en `data/raw/` (ignorada por Git y montada de solo lectura), por cada
  archivo:

```powershell
docker compose -f deploy/docker-compose.yml exec backend python manage.py ingestar_excel --archivo "/app/data/raw/San Clemente 2024.xlsx" --estacion "San Clemente"
docker compose -f deploy/docker-compose.yml exec tareas python manage.py actualizar_todo
```

Backend y tareas comparten los volúmenes `datos` (DATOS_DIR fijo en
`/app/data/cliente`) y `ficticio` (`/app/data/ficticio`). Las salidas y los modelos
persisten al recrear contenedores. Para cargar el histórico ficticio local:

```powershell
docker compose -f deploy/docker-compose.yml cp data/ficticio/cosechas.csv tareas:/app/data/ficticio/cosechas.csv
docker compose -f deploy/docker-compose.yml exec tareas python manage.py actualizar_todo
```

Consultar estado y logs, o parar conservando la base:

```powershell
docker compose -f deploy/docker-compose.yml ps
docker compose -f deploy/docker-compose.yml logs --tail=100 backend tareas
docker compose -f deploy/docker-compose.yml exec backend python manage.py createsuperuser
docker compose -f deploy/docker-compose.yml down
```

Después de cambiar credenciales o variables, recrear backend y tareas:
`docker compose -f deploy/docker-compose.yml up -d --force-recreate backend tareas`.
No usar `down -v` para una base que se quiera conservar: elimina los volúmenes.

Esta entrega cubre disponibilidad y conexión en vivo del sprint 6. El respaldo
diario con restauración y el monitoreo con alertas quedan pendientes; los
healthchecks y los volúmenes persistentes no equivalen a un respaldo ni prueban
el objetivo mensual de disponibilidad del 99 %.

---

## Cómo trabajamos

### Ramas

`main` está protegida. Nadie hace push directo. Cada ticket de Jira es una rama
corta que sale de `main` y vuelve por Pull Request.

```
feat/E1C-123-descripcion-corta     nueva funcionalidad
fix/E1C-145-descripcion-corta      corrección de bug
chore/E1C-150-descripcion-corta    configuración, dependencias, tooling
docs/E1C-152-descripcion-corta     documentación
```

Si una rama lleva más de una semana abierta, la historia estaba mal cortada.
Avísale al PO para partirla en dos tickets.

### Commits

Siempre con la clave del ticket adelante, para que Jira enlace el trabajo solo:

```
E1C-123: agregar parser de planillas de laboratorio
E1C-145: corregir zona horaria en fechas de muestreo
```

### Ciclo de trabajo

```bash
git checkout main
git pull origin main
git checkout -b feat/E1C-123-descripcion-corta

# trabajas y commiteas

git checkout main && git pull origin main
git checkout feat/E1C-123-descripcion-corta
git rebase main              # antes de abrir el PR

git push -u origin feat/E1C-123-descripcion-corta
```

Abres el PR, lo revisa un compañero del equipo, y un lead hace el merge con
squash. La rama se borra sola.

La CI (`.github/workflows/ci.yml`) corre en cada PR: `ruff check`, `ruff format --check`,
`makemigrations --check` y `pytest` contra PostgreSQL 16. Un PR con la CI en rojo no se mergea.

### Definition of Done

Un PR está listo cuando:

- Tiene tests que pasan
- Incluye migraciones si toca el esquema
- El proyecto levanta desde cero con `docker compose up` (y, si tocas la base, también sin Docker)
- No hay datos del cliente ni `.env` en el diff
- Está enlazado a un ticket de Jira

---

## Instalar los hooks de pre-commit

Recomendado para todo el equipo. Limpia el formato y, sobre todo, borra el
output de los notebooks antes de commitear.

```bash
pip install pre-commit
pre-commit install
```

---

## Datos del cliente

**Los datos de Casas Patronales nunca entran al repositorio.** Los archivos
`.xlsx`, `.xls` y `.csv` están bloqueados en `.gitignore`. Los datos reales van en
`data/raw/` (ignorado) y se comparten por el Drive del equipo. Lo que genera el backend
(`data/cliente/`, `data/ficticio/`) tampoco se sube.

Para desarrollar y escribir tests se usa el generador de datos sintéticos de
`data/synthetic/` (ver [su README](data/synthetic/README.md)).
