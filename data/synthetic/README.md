# Datos sinteticos

Aqui vive el generador de datos falsos pero realistas que permite al equipo
avanzar sin depender de la entrega de Casas Patronales.

El generador se implementa en la tarea VIG-XXX y debe producir:

- 10 temporadas de un cuartel
- muestras de laboratorio semanales desde envero hasta cosecha
- curvas de Brix con forma sigmoidal y acidez decreciente
- clima diario coherente con la zona del Maule
- fechas de cosecha plausibles

**Los datos reales del cliente NUNCA se guardan en el repositorio.**
Van en `data/raw/`, que esta ignorado por git.
