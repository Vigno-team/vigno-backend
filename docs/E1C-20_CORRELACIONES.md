# E1C-20 · Correlaciones con cosecha y calidad

Sprint 3. Cubre E1C-58 (fecha), E1C-59 (calidad) y E1C-60 (ranking, muestra y
advertencias); RF-ANA-01/02/03 y RF-PRD-08. Es un análisis exploratorio opcional.

## Dependencia pendiente: D1.3

Esta versión no dispone de modelos ni de un histórico de cosecha/calidad en
la base de datos. Se entrega un motor probado y un comando de
exportación. Para obtener resultados reales hay que recibir el histórico D1.3,
acordar la escala de calidad y seleccionar la estación representativa con el
enólogo. No se inventan resultados cuando faltan datos.

La entrada JSON es un **contrato provisional de intercambio**, no una migración
ni un reemplazo de la ingesta D1.3. Cuando esta se integre, podrá alimentar el
mismo motor. No se incorpora un endpoint público ni se cambia E1C-17.

## Entrada

Copiar `docs/plantillas/HISTORICO_COSECHA.json` a
`data/cliente/historico_cosecha.json`. La plantilla vacía se rechaza hasta que se
complete con datos y una escala acordados. `data/cliente/` ya está ignorado por
Git: guardar también allí el informe, porque contiene datos del cliente.

Forma del archivo (solo ejemplo de formato, **datos sintéticos**):

```json
{
  "version": "1",
  "escala_calidad": {
    "nombre": "Puntaje de ejemplo; sustituir por la escala acordada",
    "tipo": "numerica",
    "minimo": 0,
    "maximo": 100
  },
  "registros": [
    {
      "subzona": "Subzona de ejemplo",
      "cepa": "Cepa de ejemplo",
      "temporada": "2024-2025",
      "fecha_cosecha": "2025-03-15",
      "calidad": 85
    }
  ]
}
```

- Cada fila representa una temporada de una subzona y cepa. Los nombres deben
  coincidir exactamente; no se mezclan otras subzonas, estaciones o cepas.
- Debe existir como máximo una fila por subzona/cepa/temporada. Si hay varios
  cuarteles o eventos, D1.3 y el enólogo deben definir la agregación antes de
  exportar. El comando rechaza duplicados, sin promediarlos.
- La temporada es julio-junio, según `apps/clima/temporadas.py`. La fecha debe
  pertenecer a ella. Se transforma a días desde el 1 de julio (día cero), no a
  una fecha absoluta que confunda el paso de los años con la fecha de cosecha.
  Se cuentan días reales, incluido el 29 de febrero cuando corresponda.
- Se admiten `null` o campos ausentes para fecha y calidad. Se excluyen por
  objetivo: sin calidad aún puede analizarse fecha, y viceversa. No hay
  imputación. El valor numérico cero sí es un dato válido.
- Calidad puede ser numérica con mínimo/máximo explícitos, o **ordinal**:

```json
{
  "nombre": "Categorías acordadas con el enólogo",
  "tipo": "ordinal",
  "orden": ["baja", "media", "alta"]
}
```

En este segundo caso, `calidad` contiene una de esas cadenas. El orden debe ir
de menor a mayor calidad; no se inventa a partir del orden alfabético. Variables
nominales sin orden no están soportadas. La escala debe ser consistente entre
temporadas. Las categorías anteriores son ejemplos, no reglas del negocio.

## Ejecución en Docker

Los índices deben estar calculados previamente por el pipeline. El comando usa
`IndiceClimatico` y no recalcula índices, escribe en la base ni crea cosechas.

Desde la raíz del repositorio, sustituir los valores de estación y cepa:

```powershell
docker compose exec backend python manage.py analizar_correlaciones --historico data/cliente/historico_cosecha.json --estacion CODIGO_REAL --cepa "CEPA_REAL" --salida data/cliente/correlaciones_cosecha.json
```

`--estacion` es el **código**, no el nombre. Su subzona debe estar registrada.
Cada ejecución analiza una estación, subzona y cepa. Para volver a ejecutar,
elegir otro nombre de salida: no se sobrescriben archivos. Un error de contrato,
estación o falta total de índices produce un error y no genera un informe.
Si hay índices pero no suficientes pares válidos, se genera un informe con
estados y advertencias, sin inventar correlaciones ni un ganador.

## Cálculo y lectura del informe

Decisiones de implementación de esta entrega, pendientes de revisión de dominio:

1. Spearman para ambos objetivos: mide asociación monótona y admite una escala
   ordinal. Los empates reciben el rango medio. Conserva el signo: en fecha,
   rho negativo indica que índices mayores acompañan cosechas más tempranas;
   en calidad, el sentido depende de la escala declarada.
2. Mínimo técnico de tres pares. Con menos datos o una serie constante, `rho`
   y `p_valor` son `null` con un estado explícito. Diez temporadas es el umbral
   informativo de histórico corto, **no una garantía de potencia estadística**.
3. Significación por permutaciones de un miembro del par. Se cuenta la
   proporción con `|rho_perm| >= |rho_observado|`: todas las `n!` permutaciones
   hasta n=8 (también con empates); después, 9.999 permutaciones aleatorias,
   semilla 2026 y corrección `(extremos+1)/(9999+1)`. Así se evita un p aleatorio
   igual a cero. No se usa el p asintótico para muestras pequeñas.
4. Solo se admiten índices finitos, confiables y con completitud suficiente
   según la configuración actual; conteos inválidos también se excluyen.
   Se informan temporadas y motivos. No se mezclan versiones o parámetros
   diferentes dentro de un índice. Las fechas de ventana se comparan como mes,
   día y año relativo a la temporada; el porcentaje de completitud no forma
   parte de esa firma. Si cambia la metodología entre años, el índice queda
   excluido hasta recalcularlo homogéneamente.
5. El diagnóstico individual usa todos los pares válidos de cada índice. El
   ranking se recalcula con la **intersección de temporadas** de los índices
   evaluables. Se requieren al menos dos índices y tres temporadas comunes.
   Si una serie es constante en esa intersección, no se ordena el conjunto.
6. Se generan dos rankings separados (fecha y calidad), ordenados por `|rho|`;
   empates comparten posición. No se define una ponderación global arbitraria
   entre los dos objetivos. El ranking incluye p crudo y ajuste Holm por los
   índices comparados dentro de ese objetivo. Los p del diagnóstico son crudos;
   el ajuste no abarca ambos objetivos ni sucesivas ejecuciones con otras cepas.

Se incluyen muestra, temporadas utilizadas, datos normalizados, índices de
origen con parámetros/versiones/fecha de cálculo y SHA-256 del JSON de entrada
normalizado (no de sus bytes originales). La salida no incluye datos sintéticos
como sustituto de la base real.

**Límites de interpretación:** la primera posición no demuestra que un índice
sea estadísticamente superior a los otros. Las permutaciones suponen temporadas
independientes e intercambiables; tendencias comunes o dependencia temporal
pueden invalidar los p. Una asociación alta con pocos años es inestable.
Los índices de temporada completa pueden incorporar clima posterior a la
cosecha: esta comparación retrospectiva no valida una predicción previa a ella.
No se infiere causalidad, no se entrena un predictor y no se propone una fecha
de cosecha. Revisar con el enólogo antes de usarlo en decisiones.

Fundamento del método: [Spearman y muestras pequeñas (SciPy)](https://docs.scipy.org/doc/scipy-1.14.1/reference/generated/scipy.stats.spearmanr.html)
y [pruebas de permutación (SciPy)](https://docs.scipy.org/doc/scipy-1.14.1/reference/generated/scipy.stats.permutation_test.html).
La implementación usa la biblioteca estándar de Python; no añade SciPy ni el
entorno completo de notebooks a la imagen de la API.

## Verificación y aceptación

```powershell
docker compose exec backend pytest apps/clima/tests/test_correlaciones_cosecha.py
docker compose exec backend pytest
docker compose exec backend ruff check .
docker compose exec backend ruff format --check .
docker compose exec backend python manage.py check
docker compose exec backend python manage.py makemigrations --check --dry-run
```

Las pruebas usan exclusivamente datos sintéticos: coeficientes/p exactos
conocidos, empates, constantes, n insuficiente, Monte Carlo reproducible,
calidad ordinal, fechas, exclusiones, separación de cohortes, ranking común,
trazabilidad y ausencia de escrituras en base. No hacen falta migraciones ni
dependencias nuevas.

Para cerrar la validación funcional de E1C-20: recibir D1.3 y su escala, acordar
la unidad de agregación y estación, ejecutar con el histórico real y revisar
ambos rankings y advertencias con el enólogo. El código y las pruebas pueden
revisarse antes; los resultados de negocio siguen dependiendo de esos datos.
