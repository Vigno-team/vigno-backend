[1mdiff --git a/README.md b/README.md[m
[1mindex 9196086..eb42cae 100644[m
[1m--- a/README.md[m
[1m+++ b/README.md[m
[36m@@ -139,24 +139,7 @@[m [mo cambia `POSTGRES_PORT` en `.env`.[m
 [m
 ## Comandos frecuentes[m
 [m
[31m-### Correlación con cosecha y calidad[m
 [m
[31m-El comando `analizar_correlaciones` compara los índices calculados con un[m
[31m-histórico D1.3 y exporta dos rankings con muestra, significación y advertencias.[m
[31m-Requiere datos reales y una escala de calidad acordada; no modifica la base.[m
[31m-Consultar [contrato de entrada, ejecución y límites](docs/E1C-20_CORRELACIONES.md).[m
[31m-[m
[31m-```bash[m
[31m-docker compose up                                  # levantar[m
[31m-docker compose down                                # apagar[m
[31m-docker compose down -v                             # apagar y borrar la base[m
[31m-docker compose logs -f backend                     # ver logs[m
[31m-[m
[31m-docker compose exec backend python manage.py makemigrations[m
[31m-docker compose exec backend python manage.py migrate[m
[31m-docker compose exec backend pytest                 # correr tests[m
[31m-docker compose exec backend ruff check .           # linter[m
[31m-```[m
 ---[m
 [m
 ## Estructura[m
[36m@@ -167,7 +150,6 @@[m [mvigno/                  configuración del proyecto Django[m
 apps/[m
   clima/                serie climática, índices, resultados, API y health check[m
   ingesta/              registro de cada carga de Excel[m
[31m-  ml/                   correlaciones con cosecha (módulo Python, no es app Django)[m
 notebooks/              exploración y spikes de ciencia de datos[m
 data/synthetic/         generador de datos falsos para desarrollo[m
 tests/                  tests transversales[m
