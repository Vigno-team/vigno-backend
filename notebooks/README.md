# Notebooks

Espacio para el track de descubrimiento (spikes de ciencia de datos).

Convenciones:

- Nombrar con prefijo numerico: `01_exploracion_datos.ipynb`, `02_baseline_grados_dia.ipynb`.
- Los notebooks se commitean **sin output**. El hook `nbstripout` de pre-commit
  lo hace automaticamente; si no lo tienes instalado, corre `nbstripout <archivo>`
  antes de commitear.
- Un notebook no es un entregable de produccion. Cuando un experimento funciona,
  el codigo se migra a una app del backend; el modelo de ventana de cosecha, por
  ejemplo, vive en `apps/clima/prediccion/`.
- Nunca guardar datos del cliente aqui. Usar `data/synthetic/`.

Para trabajar con notebooks instala las dependencias del track de datos:

```bash
pip install -r requirements-ml.txt
```

## Ejemplo histórico

El notebook de comparación de Casas Patronales está en
[`docs/notebooks/03_comparacion_temporadas_estaciones.ipynb`](../docs/notebooks/03_comparacion_temporadas_estaciones.ipynb).
Es documentación de esa instancia y usa sus nombres y datos; no se ejecuta
como parte del servicio ni de la carga de organizaciones nuevas.
