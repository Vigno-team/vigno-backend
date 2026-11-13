#!/bin/bash
# Respaldos de la base, DATOS_DIR y media/ (E1C-140).
#
#   respaldos programar          un respaldo cada RESPALDOS_CADA_HORAS (24); el servicio del compose
#   respaldos respaldar          un respaldo ahora
#   respaldos restaurar ARCHIVO  reemplaza la base, DATOS_DIR y media/ con el respaldo
#   respaldos listar             los respaldos guardados
#   respaldos salud              falla si no hay un respaldo reciente (healthcheck)
#
# Cada respaldo es /respaldos/respaldo-AAAAMMDD-HHMMSSZ.tar.gz con base.dump (pg_dump -Fc),
# datos.tar, media.tar e info.txt. Se conservan los últimos RESPALDOS_CONSERVAR (14).
set -euo pipefail

DESTINO=/respaldos
CONSERVAR=${RESPALDOS_CONSERVAR:-14}
CADA_HORAS=${RESPALDOS_CADA_HORAS:-24}
export PGHOST=${POSTGRES_HOST:-db} PGUSER=$POSTGRES_USER PGDATABASE=$POSTGRES_DB
export PGPASSWORD=$POSTGRES_PASSWORD

registrar() { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] $*"; }

respaldar() {
    local marca trabajo final
    marca=$(date -u +%Y%m%d-%H%M%SZ)
    final="$DESTINO/respaldo-$marca.tar.gz"
    # Se arma en una carpeta del mismo volumen y recién al final queda con su nombre: un
    # respaldo a medias nunca parece completo.
    trabajo=$(mktemp -d "$DESTINO/.en-curso-XXXXXX")
    # La ruta se fija ahora: al salir del proceso la variable local ya no existe.
    trap "rm -rf '$trabajo'" EXIT
    registrar "Respaldando la base $PGDATABASE..."
    pg_dump --format=custom --file="$trabajo/base.dump"
    tar -C /datos -cf "$trabajo/datos.tar" .
    tar -C /media -cf "$trabajo/media.tar" .
    {
        echo "fecha: $marca"
        echo "base: $PGDATABASE"
        pg_dump --version
    } >"$trabajo/info.txt"
    tar -C "$trabajo" -czf "$trabajo/respaldo.tar.gz" base.dump datos.tar media.tar info.txt
    mv "$trabajo/respaldo.tar.gz" "$final"
    registrar "Respaldo listo: $(basename "$final") ($(du -h "$final" | cut -f1))"
    # Solo los últimos CONSERVAR; los más viejos se borran.
    ls -1t "$DESTINO"/respaldo-*.tar.gz | tail -n +"$((CONSERVAR + 1))" | while read -r viejo; do
        rm -f "$viejo"
        registrar "Borrado por antigüedad: $(basename "$viejo")"
    done
}

hay_respaldo_reciente() {
    # Un poco menos que el intervalo, para no saltarse un día por unos segundos de diferencia.
    find "$DESTINO" -maxdepth 1 -name 'respaldo-*.tar.gz' -mmin "-$(($1 * 60 - 5))" | grep -q .
}

programar() {
    trap 'exit 0' TERM INT
    registrar "Respaldos cada $CADA_HORAS h, se conservan $CONSERVAR."
    while true; do
        if ! hay_respaldo_reciente "$CADA_HORAS"; then
            # En un proceso aparte: dentro de "cmd || ..." bash ignora set -e, y un pg_dump
            # fallido dejaría un respaldo roto con apariencia de completo.
            respaldos respaldar || registrar "ERROR: el respaldo falló; se reintenta en una hora." >&2
        fi
        sleep 3600 &
        wait $!
    done
}

restaurar() {
    local archivo=${1:?Indica el archivo del respaldo}
    local trabajo
    [ -f "$archivo" ] || { echo "No existe el respaldo $archivo" >&2; exit 1; }
    trabajo=$(mktemp -d /tmp/restaurar-XXXXXX)
    trap "rm -rf '$trabajo'" EXIT
    registrar "Leyendo $(basename "$archivo")..."
    tar -xzf "$archivo" -C "$trabajo"
    for parte in base.dump datos.tar media.tar; do
        [ -f "$trabajo/$parte" ] || { echo "El respaldo no tiene $parte: no es un respaldo de este sistema." >&2; exit 1; }
    done
    cat "$trabajo/info.txt" 2>/dev/null || true
    registrar "Restaurando la base $PGDATABASE..."
    # Todo o nada: si algo falla, la base queda como estaba.
    pg_restore --clean --if-exists --no-owner --single-transaction --dbname="$PGDATABASE" "$trabajo/base.dump"
    for carpeta in datos media; do
        registrar "Restaurando $carpeta..."
        find "/destino/$carpeta" -mindepth 1 -delete
        # Sin dueños ni fecha de la carpeta raíz: quedan del usuario que restaura (el de la app).
        tar -xf "$trabajo/$carpeta.tar" -C "/destino/$carpeta" --no-same-owner --no-overwrite-dir
    done
    registrar "Restauración terminada."
}

case "${1:-programar}" in
    programar) programar ;;
    respaldar) respaldar ;;
    restaurar) shift; restaurar "$@" ;;
    listar) ls -1lh "$DESTINO"/respaldo-*.tar.gz 2>/dev/null || echo "Todavía no hay respaldos." ;;
    salud) hay_respaldo_reciente "$((CADA_HORAS + 2))" ;;
    *) echo "Uso: respaldos [programar|respaldar|restaurar ARCHIVO|listar|salud]" >&2; exit 2 ;;
esac
