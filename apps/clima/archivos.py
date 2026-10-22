import json
import os
import tempfile
from pathlib import Path


def escribir_json_atomico(ruta: Path, datos) -> None:
    """Escribe en un temporal de la misma carpeta y lo reemplaza de una vez.

    Así quien lea el archivo (la API) ve el JSON anterior o el nuevo, nunca uno a medias.
    """
    ruta = Path(ruta)
    # se serializa antes de tocar el disco para que un error de datos no deje basura
    texto = json.dumps(datos, ensure_ascii=False, indent=2, allow_nan=False)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd, temporal = tempfile.mkstemp(dir=ruta.parent, prefix=f".{ruta.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as archivo:
            archivo.write(texto)
            archivo.flush()
            os.fsync(archivo.fileno())
        # mkstemp lo crea solo para el dueño; la API puede correr con otro usuario
        os.chmod(temporal, 0o644)
        os.replace(temporal, ruta)
    except BaseException:
        Path(temporal).unlink(missing_ok=True)
        raise
