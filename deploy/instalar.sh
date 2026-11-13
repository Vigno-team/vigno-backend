#!/usr/bin/env bash
# Instala y levanta el sistema completo con un solo comando (E1C-141). Linux y macOS.
#
#   bash deploy/instalar.sh
#
# Crea deploy/.env con claves aleatorias, crea el certificado de prueba para localhost y levanta
# base, backend, tareas, respaldos y frontend. Se puede volver a correr: no cambia las claves ni
# el certificado que ya existen. El administrador por defecto lo crea el backend (E1C-138).
set -euo pipefail

cd "$(dirname "$0")/.."
ENV=deploy/.env
COMPOSE=(docker compose --env-file "$ENV" -f deploy/docker-compose.yml)

falla() { echo "ERROR: $*" >&2; exit 1; }
paso() { echo; echo "==> $*"; }

leer() { awk -F= -v k="$1" '$1 == k { sub(/^[^=]*=/, ""); print; exit }' "$ENV"; }
poner() {
    awk -v k="$1" -v v="$2" 'BEGIN { FS = "=" }
        $1 == k { print k "=" v; hecho = 1; next } { print }
        END { if (!hecho) print k "=" v }' "$ENV" >"$ENV.tmp"
    mv "$ENV.tmp" "$ENV"
}
# Solo letras y números: no hay que escaparlos en .env ni en la URL de la base.
aleatorio() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 64 || true; }

paso "Revisando Docker"
command -v docker >/dev/null || falla "No se encontró Docker. Instala Docker Desktop (Windows/Mac) o Docker Engine (Linux)."
docker info >/dev/null 2>&1 || falla "Docker no está corriendo. Ábrelo y vuelve a intentar."
docker compose version >/dev/null 2>&1 || falla "Falta Docker Compose v2 (el comando 'docker compose')."

paso "Configuración ($ENV)"
nuevo=false
if [ ! -f "$ENV" ]; then
    cp deploy/.env.example "$ENV"
    nuevo=true
    echo "Creado desde deploy/.env.example."
else
    echo "Ya existe: se conserva y solo se completan las claves vacías."
fi
for clave in SECRET_KEY POSTGRES_PASSWORD; do
    if [ -z "$(leer "$clave")" ]; then
        poner "$clave" "$(aleatorio)"
        echo "$clave generada."
    fi
done
if $nuevo; then
    # Instalación local con certificado de prueba: se entra con admin@sistema.local / admin y
    # hay que cambiar la clave al entrar (E1C-138). En un servidor público, apagar (README).
    poner ADMIN_POR_DEFECTO True
fi

paso "Frontend"
frontend=$(leer FRONTEND_DIR)
frontend=${frontend:-../../frontend}
case "$frontend" in
    /*) ruta_frontend=$frontend ;;
    *) ruta_frontend="deploy/$frontend" ;;
esac
if [ ! -f "$ruta_frontend/package.json" ]; then
    falla "No está el frontend en $ruta_frontend (FRONTEND_DIR en $ENV). Clónalo al lado del backend:
    git clone --branch develop https://github.com/Vigno-team/vigno-fronted.git \"$(cd "$(dirname "$ruta_frontend")" 2>/dev/null && pwd || echo ..)/$(basename "$ruta_frontend")\"
o cambia FRONTEND_DIR en $ENV, y vuelve a correr este instalador."
fi
echo "Encontrado en $ruta_frontend."

paso "Certificado de prueba para localhost"
if [ -f deploy/certs/fullchain.pem ] && [ -f deploy/certs/privkey.pem ]; then
    echo "Ya existe: se conserva."
else
    mkdir -p deploy/certs
    docker run --rm --mount "type=bind,source=$(pwd)/deploy/certs,target=/certs" --entrypoint sh \
        alpine/openssl:3.5.9 -c "openssl req -x509 -nodes -days 30 -newkey rsa:3072 -keyout /certs/privkey.pem -out /certs/fullchain.pem -subj /CN=localhost -addext subjectAltName=DNS:localhost,IP:127.0.0.1 && chown 101:101 /certs/privkey.pem && chmod 640 /certs/privkey.pem"
    echo "Creado (dura 30 días; el navegador avisará que no es de una autoridad pública)."
fi

paso "Construyendo y levantando (la primera vez tarda varios minutos)"
"${COMPOSE[@]}" up --build -d --wait --wait-timeout 900

puerto=$(leer HTTPS_PORT)
direccion="https://localhost"
[ -n "$puerto" ] && [ "$puerto" != "443" ] && direccion="https://localhost:$puerto"
echo
echo "Listo. Abre $direccion"
if [ "$(leer ADMIN_POR_DEFECTO)" = "True" ]; then
    echo "Entra con admin@sistema.local / admin. Te pedirá cambiar la clave en el primer ingreso."
else
    echo "Entra con la cuenta de DJANGO_SUPERUSER_EMAIL de $ENV."
fi
echo "Para apagar: docker compose --env-file $ENV -f deploy/docker-compose.yml down"
