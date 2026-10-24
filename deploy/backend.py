"""Prepara la base y los estáticos antes de iniciar el servidor WSGI."""

import os
import subprocess
import sys


def main():
    subprocess.run([sys.executable, "manage.py", "migrate", "--noinput"], check=True)
    subprocess.run([sys.executable, "manage.py", "cargar_areas_mapa"], check=True)
    subprocess.run([sys.executable, "manage.py", "collectstatic", "--noinput"], check=True)
    os.execvp(
        "gunicorn",
        [
            "gunicorn",
            "vigno.wsgi:application",
            "--bind",
            "0.0.0.0:8000",
            "--workers",
            os.getenv("GUNICORN_WORKERS", "2"),
            "--timeout",
            "120",
            "--access-logfile",
            "-",
            "--error-logfile",
            "-",
        ],
    )


if __name__ == "__main__":
    main()
