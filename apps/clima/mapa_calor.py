from copy import deepcopy

from apps.clima.models import CapaSatelital, Estacion

CAPA = "ndvi"
FUENTE = "Sentinel-2 L2A (Copernicus Data Space)"
DECIMALES = 3

# Rango fijo de la capa, no el de cada imagen: así los colores se comparan entre fechas.
ESCALA = {
    "minimo": 0.0,
    "maximo": 1.0,
    "paleta": ["#ffffcc", "#d9f0a3", "#addd8e", "#78c679", "#41ab5d", "#238443", "#005a32"],
}

MOTIVO_SIN_UBICACION = "El predio aún no tiene ubicación ni contorno cargados."
MOTIVO_SIN_IMAGEN = "Aún no hay una imagen satelital con datos válidos para este predio."
MOTIVO_INCOMPLETA = "La imagen guardada está incompleta; hay que volver a generarla."

# Campos que van en `null` cuando no hay imagen útil.
CAMPOS_DE_IMAGEN = (
    "fecha_imagen",
    "limites",
    "resolucion_m",
    "ancho",
    "alto",
    "valores",
    "escala",
    "pct_validos",
    "nubosidad_pct",
    "fuente",
    "atribucion",
    "version_calculo",
)


def _sin_imagen(estacion, motivo: str) -> dict:
    entrada = {"estacion_id": estacion.codigo, "nombre": estacion.nombre, "capa": CAPA}
    entrada.update(dict.fromkeys(CAMPOS_DE_IMAGEN))
    entrada["motivo_nulo"] = motivo
    return entrada


def entrada_mapa_calor(estacion, capa) -> dict:
    """Entrada de una estación. `capa` es la `CapaSatelital` elegida, o None si no hay."""
    if capa is None:
        motivo = MOTIVO_SIN_UBICACION if estacion.longitud is None else MOTIVO_SIN_IMAGEN
        return _sin_imagen(estacion, motivo)
    if not capa.limites_latlon:
        return _sin_imagen(estacion, MOTIVO_INCOMPLETA)

    # Se guarda como [oeste, sur, este, norte]; el contrato (y Leaflet) piden [[lat, lon], ...].
    oeste, sur, este, norte = capa.limites_latlon
    return {
        "estacion_id": estacion.codigo,
        "nombre": estacion.nombre,
        "capa": capa.capa,
        "fecha_imagen": capa.fecha_imagen.isoformat(),
        "limites": [[sur, oeste], [norte, este]],
        "resolucion_m": capa.resolucion_m,
        "ancho": capa.ancho,
        "alto": capa.alto,
        "valores": [
            [None if v is None else round(v, DECIMALES) for v in fila] for fila in capa.valores
        ],
        "escala": deepcopy(ESCALA),
        "pct_validos": capa.porcentaje_validos,
        "nubosidad_pct": capa.nubosidad_pct,
        "fuente": FUENTE,
        "atribucion": f"Contains modified Copernicus Sentinel data {capa.fecha_imagen.year}",
        "version_calculo": capa.version,
    }


def imagen_mas_reciente(estacion):
    """Última capa con al menos una celda válida en el predio, o None."""
    return (
        CapaSatelital.objects.filter(estacion=estacion, capa=CAPA, porcentaje_validos__gt=0)
        .order_by("-fecha_imagen")
        .first()
    )


def bloque_mapa_calor() -> list[dict]:
    """Una entrada por estación, en el mismo orden que `services.estaciones()`."""
    return [
        entrada_mapa_calor(estacion, imagen_mas_reciente(estacion))
        for estacion in Estacion.objects.order_by("nombre")
    ]
