import json
from dataclasses import dataclass
from pathlib import Path

# Caja que contiene a Chile continental. Sirve para detectar latitud y longitud invertidas.
LAT_MIN, LAT_MAX = -56.0, -17.0
LON_MIN, LON_MAX = -76.0, -66.0


class AreasMapaError(ValueError):
    """El archivo de áreas no cumple el formato esperado."""


@dataclass(frozen=True)
class AreaMapa:
    codigo: str
    latitud: float
    longitud: float
    geometria: dict
    estacion_dentro: bool


def _numero(valor, nombre: str, codigo: str) -> float:
    if isinstance(valor, bool) or not isinstance(valor, int | float):
        raise AreasMapaError(f"{codigo}: {nombre} debe ser un número (llegó {valor!r}).")
    return float(valor)


def validar_punto(lon: float, lat: float, donde: str) -> None:
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise AreasMapaError(f"{donde}: coordenada fuera de rango (lon={lon}, lat={lat}).")
    if not (LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX):
        raise AreasMapaError(
            f"{donde}: (lon={lon}, lat={lat}) cae fuera de Chile. "
            "GeoJSON usa el orden [longitud, latitud]: revisa que no estén invertidos."
        )


def _anillos(geometria: dict, codigo: str) -> list[list]:
    tipo = geometria.get("type")
    coords = geometria.get("coordinates")
    if tipo == "Polygon":
        poligonos = [coords]
    elif tipo == "MultiPolygon":
        poligonos = coords
    else:
        raise AreasMapaError(f"{codigo}: la geometría debe ser Polygon o MultiPolygon, no {tipo}.")
    anillos = []
    for poligono in poligonos or []:
        if not poligono:
            raise AreasMapaError(f"{codigo}: polígono sin anillos.")
        for anillo in poligono:
            if len(anillo) < 4:
                raise AreasMapaError(f"{codigo}: un anillo necesita al menos 4 puntos.")
            if anillo[0] != anillo[-1]:
                raise AreasMapaError(
                    f"{codigo}: el anillo no está cerrado (primer y último punto)."
                )
            for punto in anillo:
                if len(punto) < 2:
                    raise AreasMapaError(f"{codigo}: punto inválido {punto!r}.")
                lon = _numero(punto[0], "longitud", codigo)
                lat = _numero(punto[1], "latitud", codigo)
                validar_punto(lon, lat, f"{codigo} (contorno)")
            anillos.append(anillo)
    if not anillos:
        raise AreasMapaError(f"{codigo}: la geometría no tiene coordenadas.")
    return anillos


def punto_en_anillo(lon: float, lat: float, anillo: list) -> bool:
    """Ray casting: True si el punto está dentro del anillo."""
    dentro = False
    for (x1, y1), (x2, y2) in zip(anillo, anillo[1:], strict=False):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            dentro = not dentro
    return dentro


def _estacion_en_predio(geometria: dict, lon: float, lat: float) -> bool:
    if geometria["type"] == "Polygon":
        poligonos = [geometria["coordinates"]]
    else:
        poligonos = geometria["coordinates"]
    for poligono in poligonos:
        exterior, huecos = poligono[0], poligono[1:]
        if punto_en_anillo(lon, lat, exterior) and not any(
            punto_en_anillo(lon, lat, h) for h in huecos
        ):
            return True
    return False


def cargar_areas(ruta: Path) -> list[AreaMapa]:
    """Lee y valida el archivo. Lanza AreasMapaError con todos los problemas encontrados."""
    try:
        datos = json.loads(Path(ruta).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AreasMapaError(f"No existe {ruta}.") from exc
    except json.JSONDecodeError as exc:
        raise AreasMapaError(f"{ruta} no es un JSON válido: {exc}.") from exc

    if not isinstance(datos, dict) or datos.get("type") != "FeatureCollection":
        raise AreasMapaError("El archivo debe ser un GeoJSON de tipo FeatureCollection.")
    features = datos.get("features")
    if not isinstance(features, list) or not features:
        raise AreasMapaError("La FeatureCollection no tiene features.")

    areas, errores, vistos = [], [], set()
    for i, feature in enumerate(features):
        props = feature.get("properties") or {}
        codigo = props.get("codigo")
        if not codigo or not isinstance(codigo, str):
            errores.append(f"Feature #{i + 1}: falta properties.codigo.")
            continue
        if codigo in vistos:
            errores.append(f"{codigo}: aparece más de una vez.")
            continue
        vistos.add(codigo)
        try:
            geometria = feature.get("geometry")
            if geometria is None:
                raise AreasMapaError(f"{codigo}: falta el contorno del predio (geometry es null).")
            if props.get("latitud") is None or props.get("longitud") is None:
                raise AreasMapaError(f"{codigo}: faltan las coordenadas reales de la estación.")
            lat = _numero(props["latitud"], "latitud", codigo)
            lon = _numero(props["longitud"], "longitud", codigo)
            validar_punto(lon, lat, f"{codigo} (estación)")
            _anillos(geometria, codigo)
            dentro = _estacion_en_predio(geometria, lon, lat)
            areas.append(AreaMapa(codigo, lat, lon, geometria, dentro))
        except AreasMapaError as exc:
            errores.append(str(exc))
    if errores:
        raise AreasMapaError("\n".join(errores))
    return areas
