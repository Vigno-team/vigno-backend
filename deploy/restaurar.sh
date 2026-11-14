#!/usr/bin/env bash
# Restaura un respaldo de E1C-140 en el despliegue (Linux y macOS).
#
#   deploy/restaurar.sh respaldo-20261113-030005Z.tar.gz   un respaldo del volumen de respaldos
#   deploy/restaurar.sh ~/copias/respaldo-....tar.gz       un archivo del equipo
#   deploy/restaurar.sh --listar                           los respaldos del volumen
#   agregar --si para no pedir confirmación
#
# Reemplaza la base, DATOS_DIR y media/ por lo del respaldo. Detiene la aplicación mientras
# tanto y la vuelve a levantar al terminar.
set -euo pipefail

cd "$(dirname "$0")/.."
COMPOSE=(docker compose --env-file deploy/.env -f deploy/docker-compose.yml)

if [ "${1:-}" = "--listar" ]; then
    "${COMPOSE[@]}" --profile restaurar run --rm --no-deps --entrypoint respaldos restaurador listar
    exit 0
fi
if [ $# -lt 1 ]; then
    echo "Uso: deploy/restaurar.sh <archivo> [--si]   |   deploy/restaurar.sh --listar" >&2
    exit 2
fi

archivo=$1
montaje=()
if [ -f "$archivo" ]; then
    # Un archivo del equipo: se monta su carpeta de solo lectura.
    carpeta=$(cd "$(dirname "$archivo")" && pwd)
    montaje=(-v "$carpeta:/entrada:ro")
    ruta="/entrada/$(basename "$archivo")"
else
    ruta="/respaldos/$(basename "$archivo")"
fi

if [ "${2:-}" != "--si" ]; then
    echo "Esto REEMPLAZA la base de datos, los datos y los logos actuales por los del respaldo"
    echo "$archivo. Lo que se haya cargado después de ese respaldo se pierde."
    read -r -p "Escribe RESTAURAR para seguir: " respuesta
    [ "$respuesta" = "RESTAURAR" ] || { echo "Cancelado."; exit 1; }
fi

inicio=$(date +%s)
# Si algo falla, la aplicación no queda detenida.
trap 'echo "La restauración falló; se vuelve a levantar la aplicación." >&2; "${COMPOSE[@]}" up -d' ERR
echo "Deteniendo la aplicación..."
"${COMPOSE[@]}" stop web tareas backend respaldos
"${COMPOSE[@]}" up -d --wait db
# Así y no "${montaje[@]}": en bash 3.2 (el de macOS) un arreglo vacío con set -u da
# "unbound variable", y montaje queda vacío al restaurar una copia del volumen.
"${COMPOSE[@]}" --profile restaurar run --rm --build ${montaje[@]+"${montaje[@]}"} restaurador "$ruta"
echo "Levantando la aplicación..."
"${COMPOSE[@]}" up -d --wait --wait-timeout 600
echo "Restauración completa en $(($(date +%s) - inicio)) segundos."
