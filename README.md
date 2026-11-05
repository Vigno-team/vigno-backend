# Backend agroclimático

Sistema de apoyo a la decisión de fecha de cosecha, configurable por organización.
El perfil de Casas Patronales se entrega como una configuración de ejemplo.

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

## Configurar una organización nueva

Una instalación nueva no crea estaciones. Al arrancar, Django valida
`config/instancia.json`; si aún no existe, utiliza `config/instancia.example.json`
(organización genérica y catálogo vacío). `INSTANCIA_CONFIG` permite elegir otra
ruta. Una ruta explícita inexistente o un JSON inválido impide el arranque con un
mensaje de error. El archivo activo local está ignorado por Git.

Para crear un perfil, copia `config/instancias/ejemplo-norte/` a una carpeta propia
y edita sus cuatro archivos: `instancia.json`, `estaciones.json`,
`mapeos_estaciones.json` y `areas_mapa.json`. Las rutas de `archivos` se resuelven
desde la raíz del backend, **no desde la carpeta del perfil**. En contenedores,
usa rutas relativas a esa raíz o rutas de Linux, no rutas de Windows.

| Campo de `instancia.json` | Uso |
| --- | --- |
| `version` | Versión del contrato, actualmente `1` |
| `organizacion.nombre`, `nombre_corto` | Descripción y título de la API; nombre del servicio en health |
| `zona_horaria` | Zona IANA de la organización; también es el valor por defecto al ingerir Excel |
| `calendario.mes_inicio_temporada` | Primer mes de la temporada, de 1 a 12 |
| `calendario.mes_inicio_anio_agricola` | Primer mes de la ventana anual de lluvia |
| `calendario.meses_invierno` | Meses consecutivos y ordenados; pueden cruzar diciembre |
| `calendario.desfase_anio_invierno` | Año inicial del invierno respecto del primer año de la etiqueta: -1, 0 o 1 |
| `calendario.ventanas_indices` | Inicio y fin `[mes, día]` para `winkler`, `huglin` y `dias_calor` |
| `calendario.etapas_crecimiento` | Etapas ordenadas, sin solapamientos, con `nombre`, `inicio` y `fin` |
| `calendario.desfase_analogos_dias` | Desplazamiento de la fecha equivalente de análogos: 182 en el perfil histórico y 0 en el norte; no modifica la evaluación del modelo de referencia |
| `json_salida` | Nombre del archivo dentro de `DATOS_DIR`, sin directorios |
| `limites_geograficos` | Intervalos `latitud` y `longitud`; opcionalmente cajas `estaciones` para territorios separados |
| `archivos.mapeos`, `archivos.areas` | Archivos de columnas y contornos del perfil |

Las etiquetas conservan el formato `AAAA-AAAA+1`. En el ejemplo norte,
`2024-2025` representa enero a diciembre de 2024; su invierno es diciembre de
2023 a febrero de 2024. El mes previo al crecimiento se deriva de la primera
etapa. El JSON conserva `septiembre_mm` cuando corresponde a septiembre; en
otros calendarios entrega `precrecimiento_mm` y `mes_precrecimiento`.

Cada estación del catálogo lleva `codigo`, `nombre`, `subzona`, `propietario`,
`latitud` y `longitud`. Los códigos y nombres normalizados deben ser únicos.
Los contornos GeoJSON identifican estaciones por código. Una estación sin mapeo
propio usa `formato_estandar`. Los mapeos pueden especificar su propia zona
horaria cuando la fuente lo requiere.

En desarrollo, desde la raíz del backend:

```powershell
docker compose exec backend python manage.py cargar_instancia config/instancias/ejemplo-norte
docker compose restart backend
docker compose exec backend python manage.py actualizar_todo --sin-satelite
```

`cargar_instancia` valida el perfil completo antes de escribir. Actualiza o crea
estaciones por código, carga sus coordenadas y guarda la configuración activa.
Repetirlo no duplica registros ni borra mediciones o estaciones ajenas al catálogo.
La configuración se aplica al reiniciar los procesos. No se deben cambiar códigos
para renombrar estaciones que ya tienen histórico.

Para mantener el comportamiento de Casas Patronales:

```powershell
docker compose exec backend python manage.py cargar_instancia config/instancias/casas-patronales
docker compose restart backend
```

Las migraciones 0007, 0010 y 0011 ya no cargan catálogos en bases nuevas. No se
revierten ni se vuelven a ejecutar en bases existentes; sus estaciones y mediciones
permanecen. Antes de actualizar una instalación existente, copia su perfil a
`config/instancia.json` para conservar calendario, rutas y nombres de salida.
Después de un cambio de calendario, ejecuta `actualizar_todo --sin-satelite`
para regenerar temporadas, resúmenes, índices y JSON.

En producción, `config/` se monta en modo de solo lectura. Selecciona el perfil
en el host antes de levantar los servicios y carga el catálogo sin escribir allí:

```powershell
Copy-Item config/instancias/casas-patronales/instancia.json config/instancia.json
docker compose -f deploy/docker-compose.yml up --build -d
docker compose -f deploy/docker-compose.yml exec backend python manage.py cargar_instancia config/instancias/casas-patronales --sin-activar
docker compose -f deploy/docker-compose.yml restart backend tareas
```

Con otro perfil, sustituye la carpeta en ambos comandos. Conserva `deploy/.env`
y sus credenciales al actualizar. En instalaciones anteriores, fija
`COMPOSE_PROJECT_NAME` al nombre del proyecto existente (consultable con
`docker compose ls`) para seguir usando los mismos volúmenes de base de datos.
El nombre por defecto para instalaciones nuevas es `agroclima-produccion`.

El dataset de referencia ahora se lee de `data/referencia/`. Copia allí los
Subset y `cosechas.csv` que antes estaban en `data/ficticio/`, y ejecuta
`entrenar_cosecha` seguido de `exportar_prediccion_referencia` para regenerar las
salidas con los nombres nuevos. No borres el directorio o volumen anterior hasta
verificar la copia. En producción, el volumen `referencia` es nuevo: la sección
de despliegue explica cómo copiar el CSV. La procedencia científica y los
resultados se conservan. Los comandos antiguos siguen como alias y la ruta
`/api/v1/prediccion-ficticia` se mantiene para el frontend actual.

El contrato de configuración vive en `vigno/instancia.py` y se comparte con
E1C-96; cualquier editor de configuración debe validar con
`validar_configuracion` y escribir el archivo de forma atómica.

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
ver datos primero configura la organización y luego carga los Excel.
Para usar Casas Patronales en desarrollo:

```powershell
docker compose exec backend python manage.py cargar_instancia config/instancias/casas-patronales
docker compose restart backend
```

Para crear la primera cuenta (administrador), pon `DJANGO_SUPERUSER_EMAIL` y
`DJANGO_SUPERUSER_PASSWORD` en tu `.env` y vuelve a levantar el backend, o usa:

```bash
docker compose exec backend python manage.py createsuperuser
```

Se entra con el **correo**, así que ponle uno. Las rutas que escriben datos (cargas, alta de
estaciones y correcciones) piden token: ver [Cuentas y login](#cuentas-y-login-e1c-64).

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
| `cargar_dataset_referencia` | Une los Excel del dataset de referencia en `data/referencia/cosechas.csv` |
| `clasificar_temporadas` | Calidad de cada temporada del dataset de referencia |
| `correlacionar_madurez` | Correlaciona índices climáticos con fecha de cosecha y madurez (dataset de referencia) |
| `entrenar_cosecha [--anios-prueba <años>]` | Entrena y evalúa el modelo de ventana de cosecha (requiere `requirements-ml.txt`) |
| `exportar_prediccion_referencia` | Escribe `data/referencia/prediccion_referencia.json` con lo que dejó `entrenar_cosecha` |

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
| `API_LECTURA_PUBLICA` | `True` deja las lecturas del dashboard sin token mientras el frontend no lo mande. Si no se define, todo pide token |
| `DJANGO_SUPERUSER_EMAIL`, `DJANGO_SUPERUSER_PASSWORD` | Primer administrador: se crea al levantar el backend si no existe. Nunca cambia la clave de una cuenta existente |
| `NUM_PROXIES` | Proxies delante del backend, para el límite de intentos del login: `0` en desarrollo, `1` detrás de nginx |
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
    prediccion/         modelo de ventana de cosecha y análisis del dataset de referencia
  ingesta/              carga de Excel (carga.py), API de cargas, bitácora RegistroCarga
  cuentas/              login con correo, tokens JWT, cambio de clave y primer administrador
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

| Ruta | Método | Token | Qué devuelve |
| --- | --- | --- | --- |
| `/api/health/` | GET | No | Estado de la API y de la base |
| `/api/v1/auth/token` | POST | No | Login con correo y clave: tokens y datos de la cuenta |
| `/api/v1/auth/refresh` | POST | No | Cambia el refresco por tokens nuevos |
| `/api/v1/auth/logout` | POST | Sí | Cierra la sesión: el refresco deja de servir |
| `/api/v1/auth/yo` | GET | Sí | Datos de la cuenta del token |
| `/api/v1/auth/cambiar-clave` | POST | Sí | Cambia la clave y cierra las demás sesiones |
| `/api/v1/datos` | GET | Lectura | JSON completo; si falta, lo exporta desde la base y lo guarda. ETag y 304 si no cambió |
| `/api/v1/prediccion-ficticia` | GET | Lectura | JSON de E1C-124; 404 con motivo si no existe |
| `/api/v1/actualizacion` | GET | Lectura | Última ejecución de E1C-129, o `{"generado": null}` si aún no ha corrido |
| `/api/v1/estaciones` | GET | Lectura | Estaciones y calidad de sus datos |
| `/api/v1/estaciones` | POST | Sí | Da de alta una localidad nueva |
| `/api/v1/temporadas` | GET | Lectura | Temporadas con datos, de la más antigua a la más reciente |
| `/api/v1/temporadas/{temporada}?estacion={codigo}` | GET | Lectura | Ficha de una estación y temporada |
| `/api/v1/rachas/{temporada}?estacion={codigo}` | GET | Lectura | Rachas de calor de la temporada |
| `/api/v1/calidad/fallas?estacion={codigo}&temporada={temporada}` | GET | Lectura | Reporte de datos con falla (`&formato=csv` para CSV) |
| `/api/v1/cargas` | POST | Sí | Sube un Excel, lo valida, lo guarda y recalcula |
| `/api/v1/cargas`, `/api/v1/cargas/{id}` | GET | Sí | Historial y detalle de las cargas |
| `/api/v1/correcciones` | GET, POST | Sí | Bitácora de correcciones y nueva corrección manual |
| `/api/v1/correcciones/{id}/revertir` | POST | Sí | Revierte una corrección |

`{temporada}` va como `2024-2025` y `{codigo}` es el `id` que devuelve `/api/v1/estaciones`
(por ejemplo `cp-san-clemente-01`). Las marcadas **Lectura** piden token, salvo que
`API_LECTURA_PUBLICA=True` (los compose de desarrollo y de la demo la dejan así hasta que el
frontend mande el token). Cargas, correcciones y la cuenta siempre piden token.

Los tres endpoints de E1C-93 están documentados en `/api/docs/` y `/api/schema/`.

### Cuentas y login (E1C-64)

Se entra con **correo y clave**; cada petición lleva el token en la cabecera
`Authorization: Bearer <access>`. En `/api/docs/` el botón **Authorize** recibe el token.

```bash
curl -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/json" -d '{"email": "tu@correo.cl", "password": "..."}'
# {"access": "...", "refresh": "...", "usuario": {"id", "nombre", "email", "rol"}}
```

- **Acceso**: dura 15 minutos. **Refresco**: 8 horas; `POST /api/v1/auth/refresh` con
  `{"refresh"}` entrega un par nuevo y el refresco usado deja de servir (rota en cada uso).
- **Cerrar sesión**: `POST /api/v1/auth/logout` con `{"refresh"}` (y el token de acceso).
  Ese refresco queda en la lista negra.
- **Cambiar la clave**: `POST /api/v1/auth/cambiar-clave` con `{"clave_actual",
  "clave_nueva"}`. La nueva se valida con las reglas de Django (8+ caracteres, no común, no
  solo números, no parecida al correo). Cierra todas las sesiones de la cuenta, incluidos
  los tokens de acceso ya emitidos, y devuelve tokens nuevos.
- **`rol`**: `administrador` para el superusuario; para el resto, el grupo `editor` o `lector`
  (los crea E1C-94) o `null` si no tiene. Sale de `rol_de` en `apps/cuentas/roles.py`.

Seguridad:

- No hay registro público: las cuentas las crea un administrador. El primero sale de
  `createsuperuser` o de `DJANGO_SUPERUSER_EMAIL`/`DJANGO_SUPERUSER_PASSWORD`
  (`crear_admin_inicial`, que corre al levantar el contenedor y rechaza claves débiles).
- El correo es único sin distinguir mayúsculas (índice en la base). Una cuenta sin correo no
  puede entrar por la API.
- "El correo no existe", "clave incorrecta" y "cuenta desactivada" dan la misma respuesta
  (401) y tardan lo mismo, para no revelar qué correos tienen cuenta.
- Máximo 5 intentos de login por minuto por IP (429 después), y 5 cambios de clave por
  minuto por cuenta. Detrás de nginx la IP real sale de `X-Forwarded-For` con
  `NUM_PROXIES=1`; sin proxy delante tiene que ser `0`, o cualquiera elegiría su IP escribiendo
  esa cabecera. En el despliegue el contador vive en la base (`createcachetable`), para que
  los workers de gunicorn lo compartan.
- Los tokens se firman con `SECRET_KEY`: en el despliegue debe tener 50+ caracteres
  aleatorios o el backend no arranca. Si se filtra, cambiarla invalida todos los tokens.
- En un servidor real la API tiene que ir por HTTPS: el token viaja en cada petición.
- La clave compartida `X-Api-Key` se retiró: una clave dentro del build del frontend queda
  a la vista de cualquiera.

En el código: `apps/cuentas/` (serializers, vistas y `permisos.LecturaPublicaOAutenticado`);
la configuración está en `REST_FRAMEWORK` y `SIMPLE_JWT` de `vigno/settings/base.py`.

### Resultados por temporada (E1C-17)

La ficha usa índices reales guardados, metadatos de calidad y nulos explícitos, e incluye la
clasificación térmica e hídrica de la temporada (E1C-18). No ejecuta la ingesta ni recalcula
índices: lee lo que dejaron `generar_resumenes` y `calcular_indices`. Ver
[la guía de E1C-17](docs/E1C-17_RESULTADOS.md) para probar los endpoints y las reglas de calidad.

### JSON para el frontend (E1C-93)

`GET /api/v1/datos` sirve el archivo `json_salida` de la instancia dentro de `DATOS_DIR`
(`vigno-datos-reales.json` para Casas Patronales), que deja `actualizar_todo`
(paso `exportar_json`). Si falta, llama a `exportar()` y lo guarda atómicamente, bajo el mismo
candado de PostgreSQL que el actualizador. Lee los resultados existentes; no ingesta datos ni
entrena modelos. Un archivo corrupto o un fallo de lectura/publicación responde 503 con
`Retry-After: 30`, sin sobrescribir el archivo corrupto.

La respuesta lleva `ETag` y `Cache-Control: no-cache`: el navegador puede guardar el JSON,
pero debe revalidarlo. Al enviar `If-None-Match` con el ETag anterior, recibe 304 sin cuerpo
si no cambió. El ETag considera `generado` y el contenido, para detectar también dos
exportaciones distintas dentro del mismo segundo.

El frontend carga `/datos` al abrir y consulta `/api/v1/actualizacion` cada 60 segundos.
Si cambia `generado`, vuelve a pedir `/datos`. El estado contiene los mismos campos que
`actualizacion.json` (`generado`, `ok`, `pasos`); si no existe, devuelve `{"generado": null}`.
Una corrida fallida conserva `ok: false` y su detalle; no equivale a una publicación exitosa.

`GET /api/v1/prediccion-ficticia` entrega `data/referencia/prediccion_referencia.json` sin entrenar.
Si falta, responde 404 con `{"motivo_nulo": "Aún no se ha entrenado el modelo del dataset de referencia."}`.
El estado y la predicción también usan `Cache-Control: no-cache`; los errores, `no-store`.

`CORS_ALLOWED_ORIGINS` se configura en `.env` (o `deploy/.env`), por ejemplo
`http://localhost:5173`. CORS permite `If-None-Match` y expone `ETag` al JavaScript de Vite.

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

Las cuatro piden token, también al leer: muestran archivos y filas rechazadas.

```bash
curl -H "Authorization: Bearer $ACCESS" \
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
| `clasificar_temporadas`        | Calidad del histórico de California. Se omite si falta `data/referencia/cosechas.csv` | Sí, si hay CSV |
| `actualizar_mapa_calor`        | Capa NDVI de Sentinel-2 por estación con contorno en `config/areas_mapa.json` | No   |
| `entrenar_cosecha`             | Reentrena si existen `cosechas.csv` y scikit-learn, y el CSV es más nuevo que la evaluación | No |
| `exportar_prediccion_referencia` | Regenera `data/referencia/prediccion_referencia.json` si existe la evaluación  | No      |
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
- `actualizacion.json`: el resultado de la última corrida. Lo sirve
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
     "detalle": "omitido: no existe data/referencia/cosechas.csv"}
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

## Dataset de referencia

Mientras no haya un histórico de cosechas del cliente, el modelo se prueba con un dataset
público de California. Todo lo de esta sección usa datos ficticios para el proyecto y no
mezcla esos datos con los de las estaciones.

Fuente: Bai, Huiqing (2022), *data*, Figshare, CC BY 4.0.
https://doi.org/10.6084/m9.figshare.19807777.v1

### Cargar el histórico (E1C-78)

Descargar `data.zip` y colocar los originales `Subset1.xls`, `Subset2.xls` y
`Subset3.xls` en `data/referencia/` (ignorado por Git). No renombrar .xls a .xlsx.
Después ejecutar:

```bash
docker compose exec backend python manage.py cargar_dataset_referencia
```

Queda `data/referencia/cosechas.csv`. El lector usa `data` en Subset1/2 y los índices anuales
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
`exportar_prediccion_referencia` deja el resultado en `data/referencia/prediccion_referencia.json`.
Necesita las dependencias de ML:

```bash
docker compose exec backend pip install -r requirements-ml.txt
docker compose exec backend python manage.py entrenar_cosecha --anios-prueba 1941
docker compose exec backend python manage.py exportar_prediccion_referencia
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
git clone --branch develop https://github.com/Vigno-team/vigno-fronted.git frontend
cd vigno-backend
Copy-Item deploy/.env.example deploy/.env
```

Editar `deploy/.env`: poner claves distintas para `SECRET_KEY` (50+ caracteres, o el
backend no arranca) y `POSTGRES_PASSWORD`, y el correo y la clave del primer administrador
en `DJANGO_SUPERUSER_EMAIL` y `DJANGO_SUPERUSER_PASSWORD` (después de levantar se puede
borrar la clave del archivo). Para generar una clave se puede usar
`python -c "import secrets; print(secrets.token_urlsafe(50))"`.
Este archivo local está ignorado por Git y por la construcción de imágenes.
Las credenciales de Copernicus se agregan ahí; nunca en un commit.
Si los repositorios están en otra ubicación, ajustar `FRONTEND_DIR` (relativa
a `deploy/`, o absoluta). No reemplazar el `.env` usado para desarrollo.
Si falla la descarga de paquetes de Debian, `DEBIAN_MIRROR` permite elegir
otro [mirror oficial](https://www.debian.org/mirror/list), sin cambiar el Dockerfile.

Generar primero el certificado local siguiendo la sección **Seguridad**.
Para comprobar la configuración sin mostrar secretos ni levantar nada:

```powershell
docker compose --env-file deploy/.env -f deploy/docker-compose.yml config --quiet
```

Desde la raíz del backend:

```powershell
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up --build
```

Para dejarlo en segundo plano y esperar los healthchecks:

```powershell
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up --build -d --wait --wait-timeout 600
```

| Dirección | Contenido |
| --- | --- |
| https://localhost | Frontend de la rama develop |
| https://localhost/api/health/ | Estado de la API y conexión a PostgreSQL |
| https://localhost/api/v1/datos | JSON actualizado por el servicio tareas |
| https://localhost/api/docs/ | 404 por defecto en producción |
| https://localhost/admin/ | 404 por defecto en producción |

`WEB_PORT` cambia el puerto HTTP y `HTTPS_PORT` el HTTPS (80 y 443 por defecto).
HTTP redirige a HTTPS. Solo nginx publica puertos; PostgreSQL y Gunicorn se
comunican dentro de la red del despliegue.
El Compose de la raíz sigue siendo exclusivamente de desarrollo.
Este despliegue utiliza otra base y otros volúmenes; los datos de desarrollo
no aparecen automáticamente.

El backend usa la etapa `production` del Dockerfile, sin pytest, Ruff ni Jupyter.
Al arrancar aplica migraciones, ejecuta
collectstatic y arranca Gunicorn con DEBUG=False. `ALLOWED_HOSTS` y
`CSRF_TRUSTED_ORIGINS` se leen de `deploy/.env`; conservar localhost y 127.0.0.1
para los healthchecks. Las cookies de sesión y CSRF se envían solo por HTTPS.
Antes de arrancar, el backend exige que `check --deploy` pase sin advertencias.

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
`VITE_API_BASE_URL=/api`. El JSON se revalida mediante ETag. Si falta, la API lo
exporta desde los resultados de la base; si no puede publicarlo o el archivo es inválido,
responde 503 y Retry-After. El servicio web espera la primera actualización correcta.

### Datos y operación

La base nueva empieza sin estaciones ni mediciones. Primero configura la organización
y carga su catálogo según la sección siguiente. Después hay dos formas de cargar los Excel:

- Desde la plataforma o con `POST /api/v1/cargas`, con el token de una cuenta. Valida el
  archivo y recalcula solo.
- Con los archivos en `data/raw/` (ignorada por Git y montada de solo lectura), por cada
  archivo:

```powershell
docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec backend python manage.py ingestar_excel --archivo "/app/data/raw/San Clemente 2024.xlsx" --estacion "San Clemente"
docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec tareas python manage.py actualizar_todo
```

Backend y tareas comparten los volúmenes `datos` (DATOS_DIR fijo en
`/app/data/cliente`) y `referencia` (`/app/data/referencia`). Las salidas y los modelos
persisten al recrear contenedores. Para cargar el histórico ficticio local:

```powershell
docker compose --env-file deploy/.env -f deploy/docker-compose.yml cp data/referencia/cosechas.csv tareas:/app/data/referencia/cosechas.csv
docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec tareas python manage.py actualizar_todo
```

Consultar estado y logs, o parar conservando la base:

```powershell
docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps
docker compose --env-file deploy/.env -f deploy/docker-compose.yml logs --tail=100 backend tareas
docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec backend python manage.py createsuperuser
docker compose --env-file deploy/.env -f deploy/docker-compose.yml down
```

Después de cambiar credenciales o variables, recrear backend y tareas:
`docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --force-recreate backend tareas`.
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
(`data/cliente/`, `data/referencia/`) tampoco se sube.

Para desarrollar y escribir tests se usa el generador de datos sintéticos de
`data/synthetic/` (ver [su README](data/synthetic/README.md)).

## Demo en vivo · E1C-130

Requiere los endpoints de E1C-93 y el frontend con E1C-130 integrado en `develop`.
Durante la revisión se probaron las ramas `feat/E1C-93-endpoints-dashboard`
y `feat/E1C-130-conexion-en-vivo`; no se debe fusionar la integración antes de E1C-93.
La interfaz ya no lee un archivo copiado: consulta la API al abrir y cada 60 segundos
comprueba si cambió la publicación. Una carga o corrección refresca el dashboard al terminar.

### Preparar una demo separada

Desde `vigno-backend`, con `vigno-fronted` clonado al lado:

```powershell
Copy-Item deploy/.env.example deploy/.env.demo
```

Completar `SECRET_KEY` (50+ caracteres), `POSTGRES_PASSWORD`, `DJANGO_SUPERUSER_EMAIL`,
`DJANGO_SUPERUSER_PASSWORD` y, para obtener
una imagen nueva, las credenciales de Copernicus en `deploy/.env.demo`.
Usar `CSRF_TRUSTED_ORIGINS=https://localhost:18443` y
`CORS_ALLOWED_ORIGINS=https://localhost:18443`, y comprobar `FRONTEND_DIR`.
Generar el certificado local como se indica en **Seguridad**.
No sobrescribir el archivo si ya existe. Este archivo está ignorado por Git y Docker.

```powershell
$demo = @('--env-file', 'deploy/.env.demo', '-f', 'deploy/docker-compose.yml', '-f', 'deploy/docker-compose.demo.yml', '-p', 'vigno-e130-qa')
docker compose @demo up -d --build
```

La demo queda en `https://localhost:18443`, con PostgreSQL 16 y volúmenes separados.
El puerto HTTP 18130 redirige a HTTPS. La suite del frontend de E1C-130 fue
escrita para HTTP 18130; para ejecutarla con este despliegue necesita aceptar
la URL HTTPS y confiar en el certificado de prueba.
Para empezar de cero, usar un proyecto de demo que aún no tenga volúmenes.

1. Tener los Excel en `data/raw/` (no se suben al repositorio). Cargar inicialmente
   San Clemente y El Arenal desde **Cargar datos**, iniciando sesión y usando la vista previa.
   Para reproducir la ejecución registrada, se usaron los archivos de 2025 y 2026
   de ambas estaciones; también se pueden ingresar con `ingestar_excel`:

   ```powershell
   docker compose @demo exec backend python manage.py ingestar_excel --archivo '/app/data/raw/San Clemente 2025.xlsx' --estacion 'San Clemente'
   docker compose @demo exec backend python manage.py ingestar_excel --archivo '/app/data/raw/San Clemente 2026.xlsx' --estacion 'San Clemente'
   docker compose @demo exec backend python manage.py ingestar_excel --archivo '/app/data/raw/El Arenal 2025.xlsx' --estacion 'El Arenal'
   docker compose @demo exec backend python manage.py ingestar_excel --archivo '/app/data/raw/El Arenal 2026.xlsx' --estacion 'El Arenal'
   docker compose @demo exec backend python manage.py actualizar_todo --sin-satelite
   ```

2. Tener la capa NDVI de San Clemente y la predicción ficticia de California.
   Para obtener una capa nueva, ejecutar `actualizar_todo --forzar-satelite` en
   `tareas` con las credenciales configuradas. Para entrenar, copiar `cosechas.csv`
   de E1C-78 al volumen compartido y ejecutar el pipeline en `tareas`:

   ```powershell
   docker compose @demo cp data/referencia/cosechas.csv tareas:/app/data/referencia/cosechas.csv
   docker compose @demo exec tareas python manage.py actualizar_todo --forzar-satelite
   ```

   También se puede reutilizar el `prediccion_referencia.json` ya generado por E1C-124
   mediante `docker compose @demo cp data/referencia/prediccion_referencia.json backend:/app/data/referencia/prediccion_referencia.json`.
   La validación de esta entrega reutilizó esa salida del modelo y la capa real de
   Copernicus del 14-10-2026; comprobó su visualización, no una nueva descarga OAuth
   ni un nuevo entrenamiento. No se sustituyeron por números inventados.

3. Generar los archivos sintéticos para los casos de calidad y copiarlos al frontend:

   ```powershell
   docker compose @demo exec backend python scripts/e130_excel_prueba.py /tmp/e130-excel
   docker compose @demo cp backend:/tmp/e130-excel ../vigno-fronted/tests/.generated
   ```

   `tests/.generated` debe contener directamente los archivos. Si ya existe,
   copiar `backend:/tmp/e130-excel/.` a esa carpeta. Las fallas se ubican en octubre
   de 2024, antes de los Excel reales de 2025/2026, para probar un nulo nuevo y no la
   regla que conserva un valor ya cargado. Los archivos de prueba no se suben.

4. En `vigno-fronted`, ejecutar:

   ```powershell
   npm ci
   npm test
   # Desde E1C-64 el backend ya no acepta X-Api-Key: la suite del frontend tiene que
   # entrar con una cuenta (login) antes de volver a correr contra este backend.
   # Tras adaptar la suite al login JWT y al certificado HTTPS de la demo:
   # npm run test:e2e
   ```

   Usa Microsoft Edge instalado. Para otro navegador compatible, configurar
   `E2E_BROWSER`. La suite escribe únicamente en la demo y detiene sus tareas en
   el cuarto caso. Al terminar, desde el backend: `docker compose @demo start tareas`.
   Los reportes, capturas y trazas de Playwright quedan ignorados; pueden contener
   la clave de la demo y datos, por lo que no se adjuntan al repositorio.

### Resultado de la validación (30-10-2026)

Compose levantado con volúmenes nuevos, API sin mocks y navegador Edge.
Los nueve casos pasaron juntos en 23,8 segundos:

| Caso | Cómo comprobarlo en pantalla | Resultado |
| --- | --- | --- |
| 1. Datos reales | Abrir Resumen y elegir San Clemente o El Arenal. | Ambas estaciones y sus series llegan desde `/api/v1/datos`. |
| 2. Carga y repetición | Cargar `valido_2025.xlsx`, confirmar y repetir. | Refresco inmediato en menos de 60 s; la segunda carga no añade registros de carga. |
| 3. Satélite y predicción | Elegir San Clemente en Mapa Satelital y abrir Predicción de cosecha. | NDVI real visible; 194 predicciones con sus etiquetas de California y aviso ficticio. |
| 4. Tareas detenidas | Detener `tareas`, esperar un sondeo y navegar. | Se conserva el último JSON y el dashboard sigue funcionando. |
| 5. Fallas | Cargar `fallas_2024.xlsx`; filtrar San Clemente, temporada `2024-2025`. | Fecha inválida, nulo y fuera de rango visibles en tabla y CSV. |
| 6. Corrección | Corregir la media del 10-10-2024 a 30, con autor y fuente; volver a cargar el archivo. | Cambian índices y valores; hay marcas en históricos y resumen; la recarga conserva la corrección. |
| 7. Rechazos completos | Intentar PDF, Excel dañado, columnas ajenas y temperaturas vacías. | Motivos visibles, sin confirmación ni cambios en datos o bitácora. |
| 8. Localidad nueva | Crear una localidad con coordenadas y cargar `valido_2025.xlsx`. | Aparece en API, selectores, gráficos y mapa sin modificar configuración. |
| 9. Celdas vacías | En la localidad nueva cargar `blancos_2025.xlsx`. | La vista previa avisa; se conservan valores y no aparecen nuevas fallas. |

También pasaron 591 tests del backend (1 módulo omitido por no instalar ML en la
imagen de desarrollo), Ruff y formato. En frontend pasan 7 tests unitarios y la
compilación de producción. El lint general conserva 17 errores y 4 advertencias
preexistentes de `develop`, comprobados contra esa rama; los módulos nuevos pasan
lint. El PR de frontend identifica esa deuda sin desactivar reglas.

## Seguridad (E1C-134)

Producción usa Django 5.2 LTS y dependencias de API compatibles. La CI audita
`requirements.txt`, `requirements-dev.txt` y `requirements-ml.txt`, incluidas sus
dependencias transitivas, con `pip-audit --strict`. Una vulnerabilidad conocida
hace fallar el job. También exige `manage.py check --deploy --fail-level WARNING`
y ejecuta la suite con las dependencias de ML instaladas.

Referencias de mantenimiento: [versiones de Django](https://www.djangoproject.com/download/),
[pip-audit](https://pypi.org/project/pip-audit/) y
[nginx sin privilegios](https://github.com/nginx/docker-nginx-unprivileged).

### Certificado local

Desde la raíz del backend, crear `deploy/certs/`. En PowerShell:

```powershell
New-Item -ItemType Directory -Force deploy/certs
```

En macOS/Linux, usar `mkdir -p deploy/certs`. Después, este mismo comando Docker
funciona en las tres plataformas (no requiere instalar OpenSSL en el equipo):

```sh
docker run --rm --mount "type=bind,source=./deploy/certs,target=/certs" --entrypoint sh alpine/openssl:3.5.9 -c "openssl req -x509 -nodes -days 30 -newkey rsa:3072 -keyout /certs/privkey.pem -out /certs/fullchain.pem -subj /CN=localhost -addext subjectAltName=DNS:localhost,IP:127.0.0.1 && chown 101:101 /certs/privkey.pem && chmod 640 /certs/privkey.pem"
```

El certificado es para localhost y dura 30 días. El navegador advertirá que no
es de una autoridad pública; confiar en él solo para esta prueba local. No
repetir el comando sobre un certificado de servidor que se quiera conservar.
`deploy/certs/` queda fuera de Git y del contexto de las imágenes. Nginx monta
la carpeta de solo lectura. La utilidad de generación escribe la clave con
propietario/grupo 101 y permisos 640 para que nginx pueda leerla sin root.

Completar `deploy/.env` con secretos distintos generados con el comando de su
`.env.example`. `SECRET_KEY` (50+ caracteres) y `POSTGRES_PASSWORD` son
obligatorios. Para crear la primera cuenta, completar `DJANGO_SUPERUSER_EMAIL`
y `DJANGO_SUPERUSER_PASSWORD`. `API_LECTURA_PUBLICA=True` mantiene las lecturas
del dashboard mientras el frontend incorpora el token; las escrituras exigen JWT.
Levantar con:

```sh
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up --build -d --wait --wait-timeout 600
docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec backend python manage.py check --deploy --fail-level WARNING
```

### Certificado del servidor

Obtener el certificado de Let's Encrypt para el dominio real. Copiar el
certificado completo a `deploy/certs/fullchain.pem` y la clave privada a
`deploy/certs/privkey.pem`, con permisos de lectura para el UID/GID 101 de nginx
(640 para la clave en Linux). Copiar los archivos reales, no enlaces simbólicos
que apunten fuera de la carpeta montada. Configurar el dominio en `ALLOWED_HOSTS`
y sus orígenes HTTPS en `CSRF_TRUSTED_ORIGINS` y `CORS_ALLOWED_ORIGINS`.

Tras cada renovación, verificar y recargar:

```sh
docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec web nginx -t
docker compose --env-file deploy/.env -f deploy/docker-compose.yml exec web nginx -s reload
```

La renovación se programa en el servidor que gestione Let's Encrypt. No está
automatizada en estos contenedores. HSTS comienza en 3600 segundos e incluye
subdominios; utilizar un dominio cuyos subdominios también admitan HTTPS.
La directiva `preload` no registra el dominio en ninguna lista de navegadores;
no solicitar ese registro durante esta fase de pruebas.

### Protecciones y operación

- Nginx redirige HTTP a HTTPS y acepta TLS 1.2/1.3. Django redirige HTTP y usa
  cookies Secure. Solo confía en el protocolo que nginx sobrescribe; Gunicorn
  y PostgreSQL no publican puertos al host.
- La CSP permite los recursos locales, las teselas satelitales de
  server.arcgisonline.com y las teselas de a/b/c.tile.openstreetmap.org
  y las imágenes generadas por el mapa. Los estilos inline son necesarios para
  Leaflet y los gráficos; los scripts inline y los orígenes arbitrarios quedan
  bloqueados. Se envían `nosniff`, `Referrer-Policy`, `Permissions-Policy` y
  `X-Frame-Options: DENY`, también en respuestas de error HTTPS.
- Nginx limita `/api/v1/auth/token` y `/api/v1/auth/cambiar-clave` a 5
  peticiones/minuto por IP, con ráfaga adicional de 5 y respuesta 429. Refresco,
  consulta de cuenta y logout no comparten este límite. `/api/v1/cargas` y sus
  subrutas permiten 10/minuto, también con ráfaga de 5. Estos controles se suman
  a los de E1C-64; el login usa DatabaseCache compartida entre workers.
  El CORS permite `if-none-match` y `authorization`.
- `/admin/`, `/api/docs/` y `/api/schema/` dan 404 por defecto. Se habilitan
  explícitamente con `ADMIN_HABILITADO=True` y `DOCS_HABILITADOS=True` y recreando
  backend. La documentación Swagger usa recursos externos que la CSP de
  producción no permite; para consultarla completa usar el entorno de desarrollo.
- Backend, tareas, PostgreSQL y nginx arrancan como usuarios no root, con
  `no-new-privileges`, sin capacidades Linux, filesystem de solo lectura y
  directorios temporales en memoria. Solo los volúmenes de datos, modelos y
  estáticos necesitan escritura. Los límites son 1 GiB/2 CPU para backend,
  2 GiB/2 CPU para tareas, 768 MiB/1 CPU para PostgreSQL y 128 MiB/0,5 CPU para web.
- PostgreSQL sigue siendo PostgreSQL 16. Las imágenes de PostgreSQL, nginx,
  Node y OpenSSL tienen versión explícita; Python usa `3.11-slim-bookworm`.
  Al actualizar versiones, repetir la auditoría, la suite y la prueba de arranque.
  Las versiones y la auditoría de paquetes Python no sustituyen una revisión
  periódica de las imágenes del sistema operativo.

Los volúmenes nuevos reciben los propietarios correctos desde las imágenes.
Al reutilizar volúmenes, conservar los UID de PostgreSQL (999) y de la aplicación
(10001). Si aparece un error de permisos, revisar el volumen y su respaldo antes
de cambiar propietarios. No borrar volúmenes para resolver ese error.

### Verificación local de HTTPS

Con Python 3 en el host y un despliegue local de prueba, ejecutar:

```sh
python scripts/verificar_https.py --url https://localhost --http-url http://localhost
```

El script confía en `deploy/certs/fullchain.pem` y verifica el nombre del
certificado, redirección, cabeceras en respuestas correctas y errores, ETag,
CORS y las rutas cerradas. Hace ráfagas de GET para comprobar el 429, por lo que
solo acepta localhost; esperar un minuto antes de probar cargas manualmente.
Para otros puertos locales, pasar ambas URL y, si corresponde, `--cert`.
