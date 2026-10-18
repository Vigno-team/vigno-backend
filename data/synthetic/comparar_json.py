import argparse
import json
import sys
from pathlib import Path

# Campos que dependen de la fecha en que se exporta, no de los datos.
CAMPOS_VOLATILES = ("generado", "temporada_en_curso")

# Para nombrar los elementos de una lista de forma legible (en vez de un índice solo).
CLAVES_IDENTIFICADORAS = ("estacion_id", "id", "temporada", "fecha", "inicio")


def sin_volatiles(datos: dict) -> dict:
    return {k: v for k, v in datos.items() if k not in CAMPOS_VOLATILES}


def cargar(ruta: Path) -> dict:
    return sin_volatiles(json.loads(Path(ruta).read_text(encoding="utf-8")))


def _nombre_elemento(indice: int, elemento) -> str:
    if isinstance(elemento, dict):
        partes = [f"{c}={elemento[c]}" for c in CLAVES_IDENTIFICADORAS if c in elemento]
        if partes:
            return f"[{indice}: {', '.join(partes)}]"
    return f"[{indice}]"


def _iguales(a, b) -> bool:
    """Igualdad estricta de valores JSON; 2 y 2.0 cuentan como el mismo número."""
    es_numero = (int, float)
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, es_numero) and isinstance(b, es_numero):
        return a == b
    return type(a) is type(b) and a == b


def diferencias(esperado, real, ruta: str = "$"):
    """Genera una línea de texto por cada diferencia entre `esperado` y `real`."""
    if isinstance(esperado, dict) and isinstance(real, dict):
        for clave in sorted(esperado.keys() - real.keys()):
            yield f"{ruta}.{clave}: falta (en la referencia vale {esperado[clave]!r:.80})"
        for clave in sorted(real.keys() - esperado.keys()):
            yield f"{ruta}.{clave}: sobra (vale {real[clave]!r:.80})"
        for clave in sorted(esperado.keys() & real.keys()):
            yield from diferencias(esperado[clave], real[clave], f"{ruta}.{clave}")
    elif isinstance(esperado, list) and isinstance(real, list):
        if len(esperado) != len(real):
            yield f"{ruta}: tenía {len(esperado)} elementos y ahora tiene {len(real)}"
        for i, (a, b) in enumerate(zip(esperado, real, strict=False)):
            yield from diferencias(a, b, f"{ruta}{_nombre_elemento(i, a)}")
    elif not _iguales(esperado, real):
        yield f"{ruta}: antes {esperado!r}, ahora {real!r}"


def main():
    parser = argparse.ArgumentParser(description="Compara dos JSON de exportar_json.")
    parser.add_argument("antes", type=Path)
    parser.add_argument("despues", type=Path)
    parser.add_argument("--maximo", type=int, default=50, help="Máximo de diferencias a imprimir.")
    args = parser.parse_args()

    lista = list(diferencias(cargar(args.antes), cargar(args.despues)))
    if not lista:
        print("Sin diferencias (ignorando generado y temporada_en_curso).")
        return 0
    print(f"{len(lista)} diferencias:")
    for linea in lista[: args.maximo]:
        print(f"  {linea}")
    if len(lista) > args.maximo:
        print(f"  ... y {len(lista) - args.maximo} más (usa --maximo para ver más).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
