# VIGNO Backend

Sistema de apoyo a la decisión de fecha de cosecha para **Casas Patronales**.

Backend en Django + Django REST Framework sobre PostgreSQL, con un módulo de
análisis y machine learning. El frontend vive en el repositorio
[`vigno-frontend`](https://github.com/Vigno-team/vigno-fronted).

---

## Requisitos

Hay dos formas de trabajar. Elige una:

- **Con Docker** (recomendada): Docker, Docker Compose y Git.
- **Sin Docker** (Windows): Python 3.11, PostgreSQL 16 y Git. Ver
  [Levantar sin Docker en Windows](#levantar-sin-docker-en-windows).

---

## Levantar el proyecto (Con Docker)

```bash
git clone https://github.com/Vigno-team/vigno-backend.git
cd vigno-backend

cp .env.example .env      # completar valores si hace falta
docker compose up --build
```

Cuando termine, verifica que todo esté bien:

| URL                               | Qué es                                    |
| --------------------------------- | ----------------------------------------- |
| http://localhost:8000/api/health/ | Estado de la API y de la base de datos    |
| http://localhost:8000/api/docs/   | Documentación interactiva de la API       |
| http://localhost:8000/api/schema/ | Contrato OpenAPI (lo consume el frontend) |
| http://localhost:8000/admin/      | Admin de Django                           |

Si `/api/health/` devuelve `"status": "ok"`, tu entorno está listo.

Para crear un usuario del admin:

```bash
docker compose exec backend python manage.py createsuperuser
```

---

### Si ya tenías una base creada antes de este cambio

La base del proyecto cambió a PostgreSQL normal. Las bases creadas antes no sirven
y hay que recrearlas. No se pierde nada: la carga de datos es idempotente.

```powershell
docker compose down -v
docker compose up --build
docker compose exec backend python manage.py ingestar_excel --archivo data/raw/<archivo>.xlsx --estacion "<NOMBRE>"   # uno por cada Excel
docker compose exec backend python manage.py generar_resumenes
docker compose exec backend python manage.py calcular_indices
```

Si hay una base desplegada, también hay que recrearla y volver a cargar los datos.

**Mientras `main` siga con TimescaleDB** (hasta que `refactor` se mergee a `main`, después del 15),
las dos ramas usan la misma base de Docker (volumen `postgres_data`). Una base creada estando en
`refactor` también funciona en `main`, pero una creada en `main` vuelve a traer TimescaleDB y en
`refactor` la carga de datos puede fallar. Recrea la base solo estando en `refactor`; si la
recreaste en `main`, repite estos pasos al volver.

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

6. **Correr el pipeline** (con los Excel de `data/raw/`):

```powershell
   python manage.py ingestar_excel --archivo data/raw/<archivo>.xlsx --estacion "<NOMBRE>"
   python manage.py generar_resumenes
   python manage.py calcular_indices
```
   `calcular_indices --estacion` recibe el nombre de la estación, no el código.

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
```

---

## Estructura

```
vigno/                  configuración del proyecto Django
  settings/             base.py, development.py, production.py
apps/
  clima/                serie climática, índices, resultados, API y health check
  ingesta/              registro de cada carga de Excel
notebooks/              exploración y spikes de ciencia de datos
data/synthetic/         generador de datos falsos para desarrollo
tests/                  tests transversales
```

Solo se registran apps que tienen código en uso. Las apps vacías de la
estructura inicial (`core`, `cuartel`, `muestras`, `cosecha`) se eliminaron; el
health check que vivía en `core` ahora está en `clima`, con la misma URL.
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
`.xlsx` y `.csv` están bloqueados en `.gitignore`. Los datos reales van en
`data/raw/` (ignorado) y se comparten por el Drive del equipo.

Para desarrollar y escribir tests se usa el generador de datos sintéticos de
`data/synthetic/`.
---

## Contrato de la API

El esquema OpenAPI se genera solo desde el código y se publica en
`/api/schema/`. El equipo de frontend genera su cliente TypeScript desde ahí.

Cualquier cambio que modifique la forma de una respuesta necesita aviso al PO
del otro equipo antes de mergearse.

### Resultados por temporada

La API de resultados publica `GET /api/v1/estaciones`, `GET /api/v1/temporadas`,
`GET /api/v1/temporadas/{temporada}?estacion={codigo}` y
`GET /api/v1/rachas/{temporada}?estacion={codigo}`.
La ficha usa índices reales guardados, metadatos de calidad y nulos explícitos.
La ficha incluye la clasificación térmica e hídrica de la temporada (E1C-18).

Ver [la guía de E1C-17](docs/E1C-17_RESULTADOS.md) para ejecutar el pipeline,
probar los endpoints y revisar las dependencias de integración.

### Clasificación del histórico de California (E1C-79)

Fuente: Bai, Huiqing (2022), *data*, Figshare, CC BY 4.0.
https://doi.org/10.6084/m9.figshare.19807777.v1

`Recommend` de Subset1 describe la recomendación de los cultivares. Para el
indicador del proyecto se usa esta escala provisional, a confirmar con el enólogo: `Particularly recommended`
→ alta, `Limited recommendation` → media y `Not recommended` → baja.
`Not fully tested` y `Table grape` quedan sin clasificación y se excluyen del
denominador de `pct_alta`, al igual que los datos faltantes. Sin evaluaciones,
el porcentaje queda nulo con motivo. No es una puntuación de cata de cada vendimia.
Las etiquetas desconocidas siguen produciendo un error para evitar clasificarlas
silenciosamente. Napa solo publica °Brix, sin inventar calidad.

Tras generar `data/ficticio/cosechas.csv` con E1C-78, ejecutar:

```bash
docker compose exec backend python manage.py clasificar_temporadas
```

### JSON para el frontend

Mientras el frontend trabaje sin la API, se le entrega un JSON con los mismos bloques
que devuelven los endpoints. Se genera después de `generar_resumenes` y `calcular_indices`:

```bash
docker compose exec backend python manage.py exportar_json
```

Queda en `DATOS_DIR/vigno-datos-reales.json` (por defecto `data/cliente/`). Tiene datos
del cliente: se comparte por el Drive, no por el repo.

### Actualizar todo (E1C-129)

Un solo comando recalcula todo y deja listos los datos del frontend. Lo usan la carga
de Excel por API (E1C-66) y las tareas programadas (E1C-65):

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

- `vigno-datos-reales.json`: los datos para el frontend.
- `actualizacion.json`: el resultado de la última corrida. Lo lee
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

### Histórico de California (E1C-78)

Fuente: Bai, Huiqing (2022), *data*, Figshare, CC BY 4.0.
https://doi.org/10.6084/m9.figshare.19807777.v1

Descargar `data.zip` y colocar los originales `Subset1.xls`, `Subset2.xls` y
`Subset3.xls` en `data/ficticio/` (ignorado por Git). No renombrar .xls a .xlsx.
Instalar las dependencias actualizadas o reconstruir el backend, y ejecutar:

```bash
docker compose exec backend python manage.py cargar_dataset_ficticio
```

El lector usa `data` en Subset1/2 y los índices anuales de I:L de `Region_1`
a `Region_5` en Subset3. Obtiene el año de la fecha de cosecha en Subset1,
convierte las regiones 1–5 a I–V y conserva las etiquetas originales de Recommend.
También acepta tablas .xlsx ya normalizadas, pero no dos versiones del mismo
Subset a la vez. No sustituye índices climáticos ausentes por cero.

## Calidad del dato: rangos físicos (E1C-71)

`config/rangos_variables.json` es el catálogo único: temperaturas máxima,
mínima y media entre −15 y 50 °C; precipitación diaria entre 0 y 300 mm y
horaria entre 0 y 100 mm. Los límites están incluidos. El validador
`apps.clima.rangos.motivo_fuera_de_rango` acepta nombres canónicos y
`tmax/tmin/tmedia`, y queda disponible para las correcciones de E1C-131.

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

Después de desplegar (y tras modificar el catálogo, para revalidar históricos):

```powershell
docker compose exec backend python manage.py migrate
docker compose exec backend python manage.py validar_rangos
docker compose exec backend python manage.py generar_resumenes
docker compose exec backend python manage.py calcular_indices
```

`validar_rangos` es idempotente, actualiza solo marcas/motivos y admite
`--estacion "San Clemente"`. Las nuevas cargas validan automáticamente;
se regeneran resúmenes e índices después de cargar como en el flujo actual.

Reporte disponible:

```text
GET /api/v1/calidad/fallas?estacion=<codigo>&temporada=2024-2025
GET /api/v1/calidad/fallas?estacion=<codigo>&temporada=2024-2025&formato=csv
```

El JSON devuelve `fallas`, un `resumen` por tipo y variable y los cuatro
`tipos_incluidos`: `rechazado`, `nulo`, `sin_registro` y `fuera_de_rango`.
Cada fila identifica estación, fecha local, variable, motivo, valor original
disponible, archivo y carga. Los rechazos incluyen el número de fila del Excel.
`corregido` permanece en false hasta que exista el registro de correcciones
manuales de E1C-131. El CSV usa encabezados en español y separador `;`.
Consulta inválida responde 400 y estación inexistente 404. Es una consulta
de solo lectura, pública como el resto de la API de demo.

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


## Levantar todo (E1C-65)

Requiere Git y Docker Desktop con contenedores Linux y Compose 2.17 o posterior.
El backend y el frontend deben quedar como carpetas hermanas:

```powershell
git clone https://github.com/Vigno-team/vigno-backend.git
git clone --branch develop https://github.com/Vigno-team/vigno-fronted.git
cd vigno-backend
Copy-Item deploy/.env.example deploy/.env
```

Editar `deploy/.env`: poner claves distintas para `SECRET_KEY` y
`POSTGRES_PASSWORD`. Para generar una clave se puede usar
`python -c "import secrets; print(secrets.token_urlsafe(48))"`.
Este archivo local está ignorado por Git y por la construcción de imágenes.
Las credenciales de Copernicus se agregan ahí; nunca en un commit.
Si los repositorios están en otra ubicación, ajustar `FRONTEND_DIR` (relativa
a `deploy/`, o absoluta). No reemplazar el `.env` usado para desarrollo.
Si falla la descarga de paquetes de Debian, `DEBIAN_MIRROR` permite elegir
otro [mirror oficial](https://www.debian.org/mirror/list), sin cambiar el Dockerfile.

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
El Compose de la raíz sigue siendo exclusivamente de desarrollo y no cambia.
Este despliegue utiliza otra base y otros volúmenes; los datos de desarrollo
no aparecen automáticamente.

El backend usa la etapa `production` del Dockerfile, sin pytest, Ruff ni Jupyter.
Al arrancar aplica migraciones, carga las coordenadas de `areas_mapa.json`, ejecuta
collectstatic y arranca Gunicorn con DEBUG=False. `ALLOWED_HOSTS` y
`CSRF_TRUSTED_ORIGINS` se leen de `deploy/.env`; conservar localhost y 127.0.0.1
para los healthchecks. La configuración entregada sirve HTTP en localhost.
Si se publica con HTTPS, configurar el dominio, los orígenes HTTPS y ambas
variables `SESSION_COOKIE_SECURE` y `CSRF_COOKIE_SECURE` en True.

El servicio `tareas` usa la misma base de imagen y añade requirements-ml.txt.
Ejecuta `actualizar_todo` al partir, espera a que termine y vuelve a ejecutarlo
cada `INTERVALO_ACTUALIZACION_MIN` (360 por defecto), contado desde el fin de
la corrida. Una falla se registra en el log, deja el servicio unhealthy y se
reintenta en el siguiente intervalo; no hay ejecuciones simultáneas del programador.
La falta de CSV ficticio o credenciales satelitales sigue las reglas de omisión
de E1C-129; no se inventan resultados.

Nginx envía `/api/` a Gunicorn. También envía `/data/climateData.json` a
`/api/v1/datos`, de modo que el frontend actual recibe datos de la API y no
el archivo de ejemplo incluido en su build. El JSON no se cachea. Si aún no
existe o no es válido, la API responde 503 y Retry-After; no sirve datos ficticios
como sustituto. El servicio web espera la primera actualización correcta.

### Datos y operación

La base nueva empieza sin mediciones: la pantalla puede mostrar estaciones
sin datos hasta cargar los Excel. Colocar los archivos autorizados en `data/raw/`
(ignorada por Git y montada de solo lectura) y ejecutar, por cada archivo:

```powershell
docker compose -f deploy/docker-compose.yml exec backend python manage.py ingestar_excel --archivo "/app/data/raw/San Clemente 2024.xlsx" --estacion "San Clemente" --temporada 2024
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


## Correcciones manuales (E1C-131)

`POST /api/v1/correcciones` guarda un valor con autor y motivo y recalcula con
`actualizar_todo --sin-satelite`. La bitácora se consulta con GET en la misma ruta;
`POST /api/v1/correcciones/<id>/revertir` recupera el dato anterior y recalcula.
Las tres rutas requieren `X-Api-Key`, configurada como `INGESTA_API_KEY` en el `.env`.

Aplicar `python manage.py migrate` antes de usarlas. El reporte de fallas conserva
el problema original y marca las correcciones vigentes. Si falla el recálculo, la
API responde 503 con el ID guardado para evitar repetir el cambio. El contrato,
los ejemplos y la coordinación con la recarga de Excel están en
[docs/E1C-131_CORRECCIONES.md](docs/E1C-131_CORRECCIONES.md).
