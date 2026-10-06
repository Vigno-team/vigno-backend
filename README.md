# VIGNO Backend

Sistema de apoyo a la decisión de fecha de cosecha para **Casas Patronales**.

Backend en Django + Django REST Framework sobre PostgreSQL, con un módulo de
análisis y machine learning. El frontend vive en el repositorio
[`vigno-frontend`](https://github.com/Vigno-team/vigno-fronted).

---

## Requisitos

- Docker y Docker Compose
- Git

No necesitas tener Python ni PostgreSQL instalados en tu máquina: todo corre en
contenedores.

---

## Levantar el proyecto

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

## Comandos frecuentes

### E1C-20: correlación con cosecha y calidad

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
  core/                 health check y utilidades transversales
  cuartel/              sectores de la viña
  muestras/             análisis de laboratorio (Brix, pH, acidez)
  clima/                serie climática diaria
  cosecha/              eventos de cosecha y predicciones
  ingesta/              carga, limpieza y validación de datos
  ml/                   features, modelos y predicción
notebooks/              exploración y spikes de ciencia de datos
data/synthetic/         generador de datos falsos para desarrollo
tests/                  tests transversales
```

Cada app de dominio queda registrada desde el primer PR aunque sus modelos se
definan después, para que las migraciones y el admin ya tengan dónde apoyarse.

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
- El proyecto levanta desde cero con `docker compose up`
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

### Resultados por temporada E1C-17

La API de resultados publica `GET /api/v1/estaciones`, `GET /api/v1/temporadas`,
`GET /api/v1/temporadas/{temporada}?estacion={codigo}` y
`GET /api/v1/rachas/{temporada}?estacion={codigo}`.
La ficha usa índices reales guardados, metadatos de calidad y nulos explícitos.
La clasificación de temporada depende de E1C-18.

Ver [la guía de E1C-17](docs/E1C-17_RESULTADOS.md) para ejecutar el pipeline,
probar los endpoints y revisar las dependencias de integración.
