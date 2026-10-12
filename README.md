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

| URL | Qué es |
|---|---|
| http://localhost:8000/api/health/ | Estado de la API y de la base de datos |
| http://localhost:8000/api/docs/ | Documentación interactiva de la API |
| http://localhost:8000/api/schema/ | Contrato OpenAPI (lo consume el frontend) |
| http://localhost:8000/admin/ | Admin de Django |

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
   .venv\Scripts\Activate.ps1
   pip install -r requirements-dev.txt
```

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

### correlación con cosecha y calidad

El comando `analizar_correlaciones` compara los índices calculados con un
histórico D1.3 y exporta dos rankings con muestra, significación y advertencias.
Requiere datos reales y una escala de calidad acordada; no modifica la base.
Consultar [contrato de entrada, ejecución y límites](docs/E1C-20_CORRELACIONES.md).

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
  ml/                   correlaciones con cosecha (módulo Python, no es app Django)
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
feat/VIG-123-descripcion-corta     nueva funcionalidad
fix/VIG-145-descripcion-corta      corrección de bug
chore/VIG-150-descripcion-corta    configuración, dependencias, tooling
docs/VIG-152-descripcion-corta     documentación
```

Si una rama lleva más de una semana abierta, la historia estaba mal cortada.
Avísale al PO para partirla en dos tickets.

### Commits

Siempre con la clave del ticket adelante, para que Jira enlace el trabajo solo:

```
VIG-123: agregar parser de planillas de laboratorio
VIG-145: corregir zona horaria en fechas de muestreo
```

### Ciclo de trabajo

```bash
git checkout main
git pull origin main
git checkout -b feat/VIG-123-descripcion-corta

# trabajas y commiteas

git checkout main && git pull origin main
git checkout feat/VIG-123-descripcion-corta
git rebase main              # antes de abrir el PR

git push -u origin feat/VIG-123-descripcion-corta
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
La clasificación de temporada depende de E1C-18.

Ver [la guía de E1C-17](docs/E1C-17_RESULTADOS.md) para ejecutar el pipeline,
probar los endpoints y revisar las dependencias de integración.

### JSON para el frontend

Mientras el frontend trabaje sin la API, se le entrega un JSON con los mismos bloques
que devuelven los endpoints. Se genera después de `generar_resumenes` y `calcular_indices`:

```bash
docker compose exec backend python manage.py exportar_json
```

Queda en `data/cliente/vigno-datos-reales.json`. Tiene datos del cliente: se comparte
por el Drive, no por el repo.
