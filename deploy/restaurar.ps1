# Restaura un respaldo de E1C-140 en el despliegue (Windows).
#
#   deploy\restaurar.ps1 respaldo-20261113-030005Z.tar.gz   un respaldo del volumen de respaldos
#   deploy\restaurar.ps1 C:\copias\respaldo-....tar.gz      un archivo del equipo
#   deploy\restaurar.ps1 -Listar                            los respaldos del volumen
#   agregar -Si para no pedir confirmacion
#
# Reemplaza la base, DATOS_DIR y media/ por lo del respaldo. Detiene la aplicacion mientras
# tanto y la vuelve a levantar al terminar.
param(
    [Parameter(Position = 0)][string]$Archivo,
    [switch]$Listar,
    [switch]$Si
)
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$compose = @("compose", "--env-file", "deploy/.env", "-f", "deploy/docker-compose.yml")

function Docker-Compose {
    & docker @compose @args
    if ($LASTEXITCODE -ne 0) { throw "Fallo: docker compose $args" }
}

if ($Listar) {
    Docker-Compose --profile restaurar run --rm --no-deps --entrypoint respaldos restaurador listar
    exit 0
}
if (-not $Archivo) {
    Write-Host "Uso: deploy\restaurar.ps1 <archivo> [-Si]   |   deploy\restaurar.ps1 -Listar"
    exit 2
}

$montaje = @()
if (Test-Path -LiteralPath $Archivo -PathType Leaf) {
    # Un archivo del equipo: se monta su carpeta de solo lectura.
    $completo = (Resolve-Path -LiteralPath $Archivo).Path
    $montaje = @("-v", "$(Split-Path $completo):/entrada:ro")
    $ruta = "/entrada/$(Split-Path $completo -Leaf)"
} else {
    $ruta = "/respaldos/$(Split-Path $Archivo -Leaf)"
}

if (-not $Si) {
    Write-Host "Esto REEMPLAZA la base de datos, los datos y los logos actuales por los del respaldo"
    Write-Host "$Archivo. Lo que se haya cargado despues de ese respaldo se pierde."
    if ((Read-Host "Escribe RESTAURAR para seguir") -ne "RESTAURAR") {
        Write-Host "Cancelado."
        exit 1
    }
}

$reloj = [Diagnostics.Stopwatch]::StartNew()
Write-Host "Deteniendo la aplicacion..."
try {
    Docker-Compose stop web tareas backend respaldos
    Docker-Compose up -d --wait db
    Docker-Compose --profile restaurar run --rm --build @montaje restaurador $ruta
} catch {
    # Si algo falla, la aplicacion no queda detenida.
    Write-Host "La restauracion fallo; se vuelve a levantar la aplicacion." -ForegroundColor Red
    & docker @compose up -d
    throw
}
Write-Host "Levantando la aplicacion..."
Docker-Compose up -d --wait --wait-timeout 600
Write-Host "Restauracion completa en $([int]$reloj.Elapsed.TotalSeconds) segundos."
