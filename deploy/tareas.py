"""Ejecuta actualizar_todo al arrancar y espera entre corridas, sin solaparlas."""

import json
import math
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ESTADO = Path("/tmp/vigno-tareas.json")


def intervalo_segundos(valor):
    minutos = float(valor)
    if not math.isfinite(minutos) or minutos <= 0:
        raise ValueError("INTERVALO_ACTUALIZACION_MIN debe ser un número positivo")
    return minutos * 60


def saludable(ruta, intervalo, ahora=None):
    try:
        estado = json.loads(ruta.read_text())
        edad = (time.time() if ahora is None else ahora) - estado["termino"]
        return estado["codigo"] == 0 and 0 <= edad <= intervalo + 300
    except (OSError, ValueError, KeyError, TypeError):
        return False


def main():
    intervalo = intervalo_segundos(os.getenv("INTERVALO_ACTUALIZACION_MIN", "360"))
    if "--healthcheck" in sys.argv:
        return 0 if saludable(ESTADO, intervalo) else 1
    detener = threading.Event()
    proceso = None

    def terminar(signum, frame):
        detener.set()
        if proceso is not None and proceso.poll() is None:
            proceso.terminate()

    signal.signal(signal.SIGTERM, terminar)
    signal.signal(signal.SIGINT, terminar)
    while not detener.is_set():
        print("Iniciando actualizar_todo", flush=True)
        proceso = subprocess.Popen([sys.executable, "manage.py", "actualizar_todo"])
        codigo = proceso.wait()
        temporal = ESTADO.with_suffix(".tmp")
        temporal.write_text(json.dumps({"codigo": codigo, "termino": time.time()}))
        temporal.replace(ESTADO)
        print(
            f"actualizar_todo terminó con código {codigo}; próxima corrida en {intervalo / 60:g} minutos",
            flush=True,
        )
        detener.wait(intervalo)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
