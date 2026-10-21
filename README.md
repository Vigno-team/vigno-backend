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

Queda en `data/cliente/vigno-datos-reales.json`. Tiene datos del cliente: se comparte
por el Drive, no por el repo.
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

Los días sin registro se buscan entre la primera y la última medición de la
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
