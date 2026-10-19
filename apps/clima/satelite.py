import json
import math
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

import rasterio
import requests
from django.conf import settings
from django.utils import timezone
from rasterio.io import MemoryFile
from rasterio.warp import transform_geom

from apps.clima.models import CapaSatelital, Estacion

TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"
)
CATALOG_URL = "https://sh.dataspace.copernicus.eu/catalog/v1/search"
PROCESS_URL = "https://sh.dataspace.copernicus.eu/api/v1/process"
COLECCION = "sentinel-2-l2a"
RESOLUCION_M = 10.0
VERSION_NDVI = "ndvi-sentinel-2-l2a-v1_scl-cloud-shadow_10m"
TIMEOUT_SEGUNDOS = 60
SCL_SIN_DATO = frozenset((0, 1, 3, 7, 8, 9, 10, 11))

EVALSCRIPT_NDVI = """//VERSION=3
function setup() {
  return {
    input: [{
      bands: ["B04", "B08", "SCL", "dataMask"],
      units: ["REFLECTANCE", "REFLECTANCE", "DN", "DN"]
    }],
    output: {
      bands: 1,
      sampleType: "FLOAT32",
      nodataValue: -9999
    }
  };
}

function evaluatePixel(sample) {
  if (sample.dataMask === 0 || [0, 1, 3, 7, 8, 9, 10, 11].includes(sample.SCL)) {
    return [-9999];
  }
  const denominator = sample.B08 + sample.B04;
  if (denominator === 0) return [-9999];
  return [(sample.B08 - sample.B04) / denominator];
}
"""


class ErrorSatelite(ValueError):
    """Error al consultar o decodificar una capa satelital."""


@dataclass(frozen=True)
class GrillaNDVI:
    fecha_imagen: date
    limites: list[float]
    crs: str
    ancho: int
    alto: int
    resolucion_m: float
    valores: list[list[float | None]]
    porcentaje_validos: float
    nubosidad_pct: float
    version: str = VERSION_NDVI


def _token(client_id: str, client_secret: str) -> str:
    response = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
        },
        timeout=TIMEOUT_SEGUNDOS,
    )
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        raise ErrorSatelite("La respuesta de autenticación no contiene access_token.")
    return token


def _fecha_escena(feature: dict) -> date:
    valor = (feature.get("properties") or {}).get("datetime")
    if not valor:
        raise ErrorSatelite("La escena de Catalog no incluye properties.datetime.")
    try:
        return datetime.fromisoformat(valor.replace("Z", "+00:00")).date()
    except (AttributeError, ValueError) as exc:
        raise ErrorSatelite(f"Fecha de escena no válida: {valor!r}.") from exc


def _nubosidad(feature: dict) -> float:
    valor = (feature.get("properties") or {}).get("eo:cloud_cover")
    try:
        porcentaje = float(valor)
    except (TypeError, ValueError) as exc:
        raise ErrorSatelite("La escena de Catalog no tiene eo:cloud_cover numérico.") from exc
    if not math.isfinite(porcentaje) or not 0 <= porcentaje <= 100:
        raise ErrorSatelite(f"Nubosidad fuera de rango: {valor!r}.")
    return porcentaje


def _seleccionar_escena(geometria: dict, token: str, hoy: date) -> tuple[date, float]:
    desde = hoy - timedelta(days=29)
    hasta_dia = datetime.combine(hoy, time(23, 59, 59), UTC)
    response = requests.post(
        CATALOG_URL,
        headers={"Authorization": f"Bearer {token}"},
        json={
            "collections": [COLECCION],
            "datetime": (
                f"{datetime.combine(desde, time.min, UTC).isoformat()}/{hasta_dia.isoformat()}"
            ),
            "intersects": geometria,
            "limit": 100,
        },
        timeout=TIMEOUT_SEGUNDOS,
    )
    response.raise_for_status()
    features = response.json().get("features", [])
    candidatas = []
    for feature in features:
        propiedades = feature.get("properties") or {}
        if not propiedades.get("datetime") or propiedades.get("eo:cloud_cover") is None:
            continue
        try:
            fecha = _fecha_escena(feature)
            nubosidad = _nubosidad(feature)
        except ErrorSatelite:
            continue
        if desde <= fecha <= hoy:
            candidatas.append((nubosidad, fecha))
    if not candidatas:
        raise ErrorSatelite(f"No hay escenas Sentinel-2 L2A válidas entre {desde} y {hoy}.")
    nubosidad, fecha = min(candidatas, key=lambda item: (item[0], -item[1].toordinal()))
    return fecha, nubosidad


def _crs_utm(geometria: dict) -> str:
    longitudes = [punto[0] for anillo in _anillos_geometria(geometria) for punto in anillo]
    latitudes = [punto[1] for anillo in _anillos_geometria(geometria) for punto in anillo]
    longitud = sum(longitudes) / len(longitudes)
    latitud = sum(latitudes) / len(latitudes)
    zona = min(60, max(1, int((longitud + 180) // 6) + 1))
    epsg = (32700 if latitud < 0 else 32600) + zona
    return f"EPSG:{epsg}"


def _anillos_geometria(geometria: dict) -> list[list[list[float]]]:
    if geometria.get("type") == "Polygon":
        return geometria.get("coordinates", [])
    if geometria.get("type") == "MultiPolygon":
        return [anillo for poligono in geometria.get("coordinates", []) for anillo in poligono]
    raise ErrorSatelite("La geometría debe ser Polygon o MultiPolygon.")


def _payload_process(geometria: dict, fecha: date, crs: str) -> dict:
    geometria_utm = transform_geom("EPSG:4326", crs, geometria, precision=6)
    inicio = datetime.combine(fecha, time.min, UTC)
    fin = datetime.combine(fecha, time(23, 59, 59), UTC)
    return {
        "input": {
            "bounds": {
                "properties": {"crs": f"http://www.opengis.net/def/crs/EPSG/0/{crs.split(':')[1]}"},
                "geometry": geometria_utm,
            },
            "data": [
                {
                    "type": COLECCION,
                    "dataFilter": {
                        "timeRange": {"from": inicio.isoformat(), "to": fin.isoformat()},
                        "mosaickingOrder": "leastCC",
                        "maxCloudCoverage": 100,
                    },
                    "processing": {"upsampling": "NEAREST", "downsampling": "NEAREST"},
                }
            ],
        },
        "output": {
            "resx": RESOLUCION_M,
            "resy": RESOLUCION_M,
            "responses": [{"identifier": "default", "format": {"type": "image/tiff"}}],
        },
    }


def _leer_geotiff(contenido: bytes, fecha: date, nubosidad_pct: float) -> GrillaNDVI:
    try:
        with MemoryFile(contenido) as memoria:
            with memoria.open() as dataset:
                if dataset.count != 1:
                    raise ErrorSatelite("El GeoTIFF NDVI debe tener exactamente una banda.")
                raster = dataset.read(1).tolist()
                mascara = dataset.read_masks(1).tolist()
                nodata = dataset.nodata
                valores = []
                validos = 0
                for fila, fila_mascara in zip(raster, mascara, strict=True):
                    fila_valores = []
                    for valor, mascara_valor in zip(fila, fila_mascara, strict=True):
                        if (
                            not mascara_valor
                            or not math.isfinite(float(valor))
                            or (nodata is not None and valor == nodata)
                        ):
                            fila_valores.append(None)
                        else:
                            fila_valores.append(float(valor))
                            validos += 1
                    valores.append(fila_valores)
                total = dataset.width * dataset.height
                transform = dataset.transform
                if dataset.crs is None:
                    raise ErrorSatelite("El GeoTIFF no contiene CRS.")
                return GrillaNDVI(
                    fecha_imagen=fecha,
                    limites=[
                        float(dataset.bounds.left),
                        float(dataset.bounds.bottom),
                        float(dataset.bounds.right),
                        float(dataset.bounds.top),
                    ],
                    crs=dataset.crs.to_string(),
                    ancho=dataset.width,
                    alto=dataset.height,
                    resolucion_m=round(max(abs(transform.a), abs(transform.e)), 6),
                    valores=valores,
                    porcentaje_validos=round(validos / total * 100, 1) if total else 0.0,
                    nubosidad_pct=nubosidad_pct,
                )
    except (rasterio.errors.RasterioError, ValueError) as exc:
        if isinstance(exc, ErrorSatelite):
            raise
        raise ErrorSatelite(f"No se pudo leer el GeoTIFF NDVI: {exc}.") from exc


def obtener_grilla_ndvi(
    geometria: dict,
    hoy: date | None = None,
    client_id: str | None = None,
    client_secret: str | None = None,
) -> GrillaNDVI:
    hoy = hoy or timezone.localdate()
    client_id = client_id if client_id is not None else settings.CDSE_CLIENT_ID
    client_secret = client_secret if client_secret is not None else settings.CDSE_CLIENT_SECRET
    if not client_id or not client_secret:
        raise ErrorSatelite("Configura CDSE_CLIENT_ID y CDSE_CLIENT_SECRET en el entorno.")

    crs = _crs_utm(geometria)
    token = _token(client_id, client_secret)
    fecha, nubosidad = _seleccionar_escena(geometria, token, hoy)
    response = requests.post(
        PROCESS_URL,
        headers={"Authorization": f"Bearer {token}", "Accept": "image/tiff"},
        files={
            "request": (None, json.dumps(_payload_process(geometria, fecha, crs))),
            "evalscript": (None, EVALSCRIPT_NDVI),
        },
        timeout=TIMEOUT_SEGUNDOS,
    )
    response.raise_for_status()
    return _leer_geotiff(response.content, fecha, nubosidad)


def actualizar_capa_ndvi(estacion: Estacion, geometria: dict) -> CapaSatelital:
    grilla = obtener_grilla_ndvi(geometria)
    capa, _ = CapaSatelital.objects.update_or_create(
        estacion=estacion,
        capa="ndvi",
        fecha_imagen=grilla.fecha_imagen,
        defaults={
            "limites": grilla.limites,
            "crs": grilla.crs,
            "ancho": grilla.ancho,
            "alto": grilla.alto,
            "resolucion_m": grilla.resolucion_m,
            "valores": grilla.valores,
            "porcentaje_validos": grilla.porcentaje_validos,
            "nubosidad_pct": grilla.nubosidad_pct,
            "version": grilla.version,
        },
    )
    return capa
