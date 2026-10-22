# E1C-85 · Ventana de cosecha: demostración con California

Este comando entrena y evalúa sobre el histórico de Amerine & Winkler del
CSV generado por E1C-78, publicado por Bai et al. (2022), *Scientific Data*
9:271. No predice temporadas de VIGNO ni transforma fechas al hemisferio sur.
Las filas de Napa quedan reservadas para la validación de E1C-87.

## Ejecutar

Desde la raíz del repositorio, con Docker iniciado y el CSV local en
`data/ficticio/cosechas.csv`:

```powershell
docker compose exec backend pip install -r requirements-ml.txt
docker compose exec backend pytest apps/clima/tests/prediccion/test_prediccion.py
docker compose exec backend python manage.py entrenar_cosecha --anios-prueba 1941
```

El argumento admite varios años completos. Los años indicados no participan
en el entrenamiento del preprocesamiento, de los modelos ni del promedio
regional. No se hace una partición aleatoria de filas.

## Datos, modelos y salida

- Variables: GST, Winkler, Huglin, región I–V y color. Región y color se
  codifican mediante one-hot dentro de cada modelo.
- Se ignoran las demás columnas del CSV, incluidas °Brix, acidez, pH,
  alcohol y fechas trasladadas al hemisferio sur.
- Se descartan filas incompletas para las variables, objetivo o identidad;
  la salida informa cuántas. Valores no finitos, regiones/colores
  desconocidos y fechas inválidas producen un error.
- Se entrenan Random Forest (100 árboles, semilla 42) y regresión lineal.
  La base ingenua es la media del día de cosecha por región, calculada
  exclusivamente en las mismas filas válidas del entrenamiento.
- Las tres métricas usan exactamente las mismas filas de prueba.
  El JSON incluye MAE y RMSE en días, tamaño de muestra y comparación del
  Random Forest contra la base por ambas métricas.
- Cada fila conserva `fuente`, `region`, `anio`, `cultivar` y `color`;
  incluye DOY real, estimado, diferencia firmada (estimado menos real),
  fecha real y ventana de percentiles 10–90 de los árboles.
- El centro usa la predicción media del Random Forest. Las fechas usan el
  año real de California. La dispersión entre árboles **no es un intervalo
  de confianza calibrado**.
- Se exportan las importancias del Random Forest agrupadas por variable
  original y los coeficientes e intercepto de la regresión lineal. Estos
  coeficientes dependen de la codificación y la correlación entre índices;
  no son efectos causales ni un ranking de importancia.

El resultado está en `data/ficticio/prediccion_cosecha_california.json`,
con `datos_ficticios: true`, la referencia bibliográfica y los años evaluados.
El archivo joblib versionado en `apps/ml/artifacts/` guarda ambos modelos,
las medias regionales, fecha UTC, variables y metadatos de validación.
Ambas salidas están ignoradas por Git.

## Dependencias y pruebas

La API y la CI base no necesitan scikit-learn. Se fija únicamente en
`requirements-ml.txt`. Sin esa dependencia, pytest omite el módulo de
pruebas de ML y el comando devuelve `CommandError` con instrucciones.

Las pruebas cubren separación temporal, ausencia de fuga del objetivo de
prueba, metadatos originales, métricas reconstruidas desde las predicciones,
coeficientes, exclusión de Napa, filas incompletas, fechas, errores y
persistencia de las salidas. No hay migraciones.

E1C-124 debe consumir este contrato de demostración de California.
La aplicación al cliente necesita su propio histórico y queda fuera del
alcance de Sprint 5.
